from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import User, get_async_session
from app.models import GmailConnection
from app.schemas import (
    ConnectedGmailWatchRequest,
    ConnectedGmailTriageRequest,
    GmailCategory,
    GmailConnectUrlResponse,
    GmailConnectionStatusResponse,
    GmailTriageResponse,
    GmailWatchResponse,
    GmailWebhookPayload,
    GmailWebhookResponse,
)
from app.services.email_triage import (
    build_triage_report,
    classifications_to_priority_map,
    create_email_triage_client,
)
from app.services.gmail import (
    GmailClient,
    categories_from_csv,
    categories_to_csv,
    decode_pubsub_data,
)
from app.services.google_oauth import (
    build_google_oauth_url,
    exchange_code_for_tokens,
    parse_oauth_state,
    refresh_access_token,
)
from app.users import current_active_user

router = APIRouter(tags=["email"])


@router.get("/gmail/connect-url", response_model=GmailConnectUrlResponse)
async def get_gmail_connect_url(user: User = Depends(current_active_user)):
    return GmailConnectUrlResponse(url=build_google_oauth_url(str(user.id)))


@router.get("/gmail/status", response_model=GmailConnectionStatusResponse)
async def get_gmail_status(
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    connection = await _get_user_gmail_connection(db, user.id)
    if not connection:
        return GmailConnectionStatusResponse(connected=False)

    return GmailConnectionStatusResponse(
        connected=True,
        email_address=connection.email_address,
        categories=categories_from_csv(connection.categories),
    )


@router.get("/gmail/oauth/callback")
async def gmail_oauth_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_async_session),
):
    user_id = parse_oauth_state(state)
    tokens = await run_in_threadpool(exchange_code_for_tokens, code)
    client = GmailClient(access_token=tokens["access_token"])
    profile = await run_in_threadpool(client.get_profile)

    result = await db.execute(
        select(GmailConnection).filter(
            GmailConnection.email_address == profile["emailAddress"],
            GmailConnection.user_id == UUID(user_id),
        )
    )
    connection = result.scalars().first()
    if not connection:
        connection = GmailConnection(
            user_id=UUID(user_id),
            email_address=profile["emailAddress"],
        )
        db.add(connection)

    connection.access_token = tokens["access_token"]
    if tokens.get("refresh_token"):
        connection.refresh_token = tokens["refresh_token"]
    connection.categories = categories_to_csv(
        [GmailCategory.primary, GmailCategory.updates, GmailCategory.promotions]
    )

    await db.commit()
    return RedirectResponse(f"{settings.FRONTEND_URL}/dashboard/gmail?connected=1")


@router.post("/gmail/triage-connected", response_model=GmailTriageResponse)
async def triage_connected_gmail(
    payload: ConnectedGmailTriageRequest,
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    connection = await _get_user_gmail_connection(db, user.id)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect Gmail before sorting email.",
        )

    if connection.refresh_token:
        tokens = await run_in_threadpool(refresh_access_token, connection.refresh_token)
        connection.access_token = tokens["access_token"]
        await db.commit()

    gmail_client = GmailClient(access_token=connection.access_token)
    messages = await run_in_threadpool(
        gmail_client.search_messages,
        payload.search_query,
        payload.max_results,
    )
    client = create_email_triage_client()
    classifications = await run_in_threadpool(
        client.classify_messages,
        messages,
        payload,
    )

    if not payload.dry_run:
        priority_map = classifications_to_priority_map(classifications)
        await run_in_threadpool(
            gmail_client.apply_category_priority_labels,
            messages,
            priority_map,
        )

    result = build_triage_report(messages, classifications, payload.dry_run)

    return GmailTriageResponse(result=result)


@router.post("/gmail/watch-connected", response_model=GmailWatchResponse)
async def watch_connected_gmail_messages(
    payload: ConnectedGmailWatchRequest,
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    topic_name = payload.topic_name or settings.GMAIL_PUBSUB_TOPIC_NAME
    if not topic_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gmail Pub/Sub topic is required.",
        )

    connection = await _get_user_gmail_connection(db, user.id)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect Gmail before starting Gmail watch.",
        )

    if connection.refresh_token:
        tokens = await run_in_threadpool(refresh_access_token, connection.refresh_token)
        connection.access_token = tokens["access_token"]
        await db.commit()

    client = GmailClient(access_token=connection.access_token)
    profile = await run_in_threadpool(client.get_profile)
    watch_response = await run_in_threadpool(
        client.watch_mailbox,
        topic_name,
        payload.categories,
    )
    email_address = profile["emailAddress"]

    connection.email_address = email_address
    connection.history_id = watch_response.get("historyId")
    connection.watch_expiration = watch_response.get("expiration")
    connection.categories = categories_to_csv(payload.categories)

    await db.commit()

    return GmailWatchResponse(
        email_address=email_address,
        history_id=connection.history_id,
        expiration=connection.watch_expiration,
        categories=payload.categories,
    )


@router.post("/gmail/webhook", response_model=GmailWebhookResponse)
async def gmail_webhook(
    payload: GmailWebhookPayload,
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_async_session),
):
    if settings.GMAIL_WEBHOOK_TOKEN and token != settings.GMAIL_WEBHOOK_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Gmail webhook token.",
        )

    notification = decode_pubsub_data(payload.message.data)
    email_address = notification.get("emailAddress")
    notification_history_id = notification.get("historyId")
    if not email_address or not notification_history_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pub/Sub message did not include a Gmail emailAddress and historyId.",
        )

    result = await db.execute(
        select(GmailConnection).filter(
            GmailConnection.email_address == email_address,
        )
    )
    connection = result.scalars().first()
    if not connection:
        return GmailWebhookResponse(processed=False, email_address=email_address)

    if connection.refresh_token:
        tokens = await run_in_threadpool(refresh_access_token, connection.refresh_token)
        connection.access_token = tokens["access_token"]
        await db.commit()

    start_history_id = connection.history_id or notification_history_id
    client = GmailClient(access_token=connection.access_token)
    messages, latest_history_id = await run_in_threadpool(
        client.pull_history,
        start_history_id,
        categories_from_csv(connection.categories),
    )

    if settings.OPENAI_EMAIL_TRIAGE_ON_WEBHOOK and messages:
        triage_payload = ConnectedGmailTriageRequest(
            search_query="gmail webhook history",
            max_results=len(messages),
            dry_run=False,
        )
        triage_client = create_email_triage_client()
        classifications = await run_in_threadpool(
            triage_client.classify_messages,
            messages,
            triage_payload,
        )
        await run_in_threadpool(
            client.apply_category_priority_labels,
            messages,
            classifications_to_priority_map(classifications),
        )

    connection.history_id = latest_history_id or notification_history_id
    await db.commit()

    return GmailWebhookResponse(
        processed=True,
        email_address=email_address,
        pulled=len(messages),
    )


async def _get_user_gmail_connection(
    db: AsyncSession,
    user_id: UUID,
) -> GmailConnection | None:
    result = await db.execute(
        select(GmailConnection).filter(GmailConnection.user_id == user_id)
    )
    return result.scalars().first()
