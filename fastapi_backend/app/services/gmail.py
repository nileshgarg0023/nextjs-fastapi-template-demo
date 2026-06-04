import json
import logging
import base64
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import HTTPException, status

from app.config import settings
from app.schemas import EmailPriority, GmailCategory, GmailMessageRead

logger = logging.getLogger(__name__)

GMAIL_CATEGORY_LABELS = {
    GmailCategory.primary: "CATEGORY_PRIMARY",
    GmailCategory.promotions: "CATEGORY_PROMOTIONS",
    GmailCategory.updates: "CATEGORY_UPDATES",
}


@dataclass(slots=True)
class GmailClient:
    access_token: str
    base_url: str = settings.GMAIL_API_BASE_URL

    def search_messages(
        self,
        query_text: str,
        max_results: int,
    ) -> list[GmailMessageRead]:
        query = urlencode({"q": query_text, "maxResults": max_results})
        data = self._request(f"/users/me/messages?{query}")

        messages: list[GmailMessageRead] = []
        for message_ref in data.get("messages", []):
            messages.append(self._get_message(message_ref["id"]))
        return messages

    def apply_category_priority_labels(
        self,
        messages: list[GmailMessageRead],
        classifications: dict[str, EmailPriority],
    ) -> None:
        messages_by_id = {message.gmail_id: message for message in messages}
        label_names = {
            message_id: _category_priority_label(
                messages_by_id[message_id].category,
                priority,
            )
            for message_id, priority in classifications.items()
            if message_id in messages_by_id
        }
        all_label_names = [
            _category_priority_label(category, priority)
            for category in GmailCategory
            for priority in EmailPriority
        ]
        label_ids = {
            label_name: self._ensure_label(label_name)
            for label_name in all_label_names
        }

        for message_id, label_name in label_names.items():
            self._request(
                f"/users/me/messages/{message_id}/modify",
                method="POST",
                body={
                    "addLabelIds": [label_ids[label_name]],
                    "removeLabelIds": [
                        label_id
                        for candidate_name, label_id in label_ids.items()
                        if candidate_name != label_name
                    ],
                },
            )

    def get_profile(self) -> dict[str, Any]:
        return self._request("/users/me/profile")

    def watch_mailbox(
        self,
        topic_name: str,
        categories: list[GmailCategory],
    ) -> dict[str, Any]:
        return self._request(
            "/users/me/watch",
            method="POST",
            body={
                "topicName": topic_name,
                "labelIds": [GMAIL_CATEGORY_LABELS[category] for category in categories],
            },
        )

    def pull_history(
        self,
        start_history_id: str,
        categories: list[GmailCategory],
    ) -> tuple[list[GmailMessageRead], str | None]:
        query = urlencode(
            {
                "startHistoryId": start_history_id,
                "historyTypes": "messageAdded",
            }
        )
        data = self._request(f"/users/me/history?{query}")
        latest_history_id = data.get("historyId")
        messages: list[GmailMessageRead] = []
        seen_message_ids: set[str] = set()

        for history_record in data.get("history", []):
            for added in history_record.get("messagesAdded", []):
                message_ref = added.get("message", {})
                message_id = message_ref.get("id")
                if not message_id or message_id in seen_message_ids:
                    continue

                category = _category_from_label_ids(
                    message_ref.get("labelIds", []), categories
                )
                if not category:
                    continue

                message = self._get_message(message_id, category)
                messages.append(message)
                seen_message_ids.add(message_id)
                logger.info(
                    "Pulled Gmail webhook message: category=%s id=%s from=%s subject=%s",
                    message.category,
                    message.gmail_id,
                    message.sender,
                    message.subject,
                )
                logger.info(
                    "Gmail webhook message body preview: category=%s id=%s snippet=%s",
                    message.category,
                    message.gmail_id,
                    message.snippet,
                )

        return messages, latest_history_id

    def _get_message(
        self,
        message_id: str,
        category: GmailCategory | None = None,
    ) -> GmailMessageRead:
        query = urlencode({"format": "full"})
        data = self._request(f"/users/me/messages/{message_id}?{query}")
        headers = _headers_by_name(data.get("payload", {}).get("headers", []))
        resolved_category = category or _category_from_label_ids(
            data.get("labelIds", []),
            [GmailCategory.primary, GmailCategory.updates, GmailCategory.promotions],
        )

        return GmailMessageRead(
            gmail_id=data["id"],
            thread_id=data.get("threadId"),
            category=resolved_category or GmailCategory.primary,
            subject=headers.get("subject"),
            sender=headers.get("from"),
            received_at=_normalize_date(headers.get("date")),
            snippet=data.get("snippet"),
            body_content=_extract_body_content(data.get("payload", {})),
        )

    def _ensure_label(self, label_name: str) -> str:
        labels = self._request("/users/me/labels").get("labels", [])
        for label in labels:
            if label.get("name") == label_name:
                return label["id"]

        label = self._request(
            "/users/me/labels",
            method="POST",
            body={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        return label["id"]

    def _request(
        self,
        path: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        encoded_body = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=encoded_body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = _read_error_detail(exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Gmail API request failed: {detail}",
            ) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gmail API request could not be completed.",
            ) from exc


def _headers_by_name(headers: list[dict[str, str]]) -> dict[str, str]:
    return {
        header["name"].lower(): header.get("value", "")
        for header in headers
        if "name" in header
    }


def _normalize_date(value: str | None) -> str | None:
    if not value:
        return None

    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return value


def _extract_body_content(payload: dict[str, Any]) -> str | None:
    chunks = list(_extract_text_parts(payload, preferred_mime_type="text/plain"))
    if not chunks:
        chunks = list(_extract_text_parts(payload, preferred_mime_type="text/html"))
    if not chunks:
        return None

    return "\n\n".join(_clean_body_text(chunk) for chunk in chunks if chunk.strip())


def _extract_text_parts(payload: dict[str, Any], preferred_mime_type: str):
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")
    if body_data and mime_type == preferred_mime_type:
        yield _decode_message_body(body_data)

    for part in payload.get("parts", []):
        yield from _extract_text_parts(part, preferred_mime_type)


def _decode_message_body(value: str) -> str:
    padded_value = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded_value.encode("utf-8")).decode(
        "utf-8", errors="ignore"
    )


def _clean_body_text(value: str) -> str:
    text = re.sub(r"<(script|style).*?</\1>", " ", value, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _read_error_detail(exc: HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode("utf-8"))
        return body.get("error", {}).get("message") or exc.reason
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return exc.reason


def decode_pubsub_data(data: str) -> dict[str, Any]:
    padded_data = data + "=" * (-len(data) % 4)
    decoded = base64.urlsafe_b64decode(padded_data.encode("utf-8"))
    return json.loads(decoded.decode("utf-8"))


def categories_to_csv(categories: list[GmailCategory]) -> str:
    return ",".join(category.value for category in categories)


def categories_from_csv(value: str | None) -> list[GmailCategory]:
    if not value:
        return [GmailCategory.primary, GmailCategory.promotions, GmailCategory.updates]

    return [GmailCategory(item) for item in value.split(",") if item]


def _category_from_label_ids(
    label_ids: list[str],
    categories: list[GmailCategory],
) -> GmailCategory | None:
    labels = set(label_ids)
    for category in categories:
        if GMAIL_CATEGORY_LABELS[category] in labels:
            return category
    return None


def _category_priority_label(
    category: GmailCategory,
    priority: EmailPriority,
) -> str:
    category_name = {
        GmailCategory.primary: "Primary",
        GmailCategory.updates: "Updates",
        GmailCategory.promotions: "Promotions",
    }[category]
    priority_name = {
        EmailPriority.high: "High",
        EmailPriority.medium: "Medium",
        EmailPriority.low: "Low",
    }[priority]
    return f"{category_name}/{priority_name}"
