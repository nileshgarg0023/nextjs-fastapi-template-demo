import uuid
from enum import StrEnum

from fastapi_users import schemas
from pydantic import BaseModel, Field
from uuid import UUID


class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass


class ItemBase(BaseModel):
    name: str
    description: str | None = None
    quantity: int | None = None


class ItemCreate(ItemBase):
    pass


class ItemRead(ItemBase):
    id: UUID
    user_id: UUID

    model_config = {"from_attributes": True}


class GmailCategory(StrEnum):
    primary = "primary"
    promotions = "promotions"
    updates = "updates"


class GmailMessageRead(BaseModel):
    gmail_id: str
    thread_id: str | None = None
    category: GmailCategory
    subject: str | None = None
    sender: str | None = None
    received_at: str | None = None
    snippet: str | None = None
    body_preview: str | None = None


class ConnectedGmailWatchRequest(BaseModel):
    topic_name: str | None = Field(
        default=None,
        description="Google Cloud Pub/Sub topic, e.g. projects/my-project/topics/gmail.",
    )
    categories: list[GmailCategory] = Field(
        default_factory=lambda: [
            GmailCategory.primary,
            GmailCategory.updates,
            GmailCategory.promotions,
        ]
    )


class GmailWatchResponse(BaseModel):
    email_address: str
    history_id: str
    expiration: str | None = None
    categories: list[GmailCategory]


class GmailWebhookMessage(BaseModel):
    data: str
    messageId: str | None = None
    publishTime: str | None = None


class GmailWebhookPayload(BaseModel):
    message: GmailWebhookMessage
    subscription: str | None = None


class GmailWebhookResponse(BaseModel):
    processed: bool
    email_address: str | None = None
    pulled: int = 0


class EmailPriority(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class GmailTriageResponse(BaseModel):
    result: str


class GmailConnectUrlResponse(BaseModel):
    url: str


class GmailConnectionStatusResponse(BaseModel):
    connected: bool
    email_address: str | None = None
    categories: list[GmailCategory] = Field(default_factory=list)


class ConnectedGmailTriageRequest(BaseModel):
    search_query: str = Field(
        default="newer_than:1d",
        description="Gmail search query for the messages OpenAI should triage.",
    )
    max_results: int = Field(default=50, ge=1, le=200)
    dry_run: bool = True
    user_focus: str = (
        "Primary emails: high if they need immediate attention, are important, "
        "mention a deadline or time within the next 1-2 days, contain a clear "
        "action item, or involve legal, finance, security, customers, or a direct "
        "human request. Primary emails are medium if they can wait 3-4 days or "
        "later. Primary emails are low if they are not important. Updates default "
        "to medium, but can be high for urgent action/deadlines or low for noise. "
        "Promotions default to low, but can be medium or high when they contain "
        "real urgency, account/payment/legal/security relevance, a near deadline, "
        "or match the user's active focus."
    )
