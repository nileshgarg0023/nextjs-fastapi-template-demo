import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from fastapi import HTTPException, status

from app.config import settings
from app.schemas import (
    ConnectedGmailTriageRequest,
    EmailPriority,
    GmailMessageRead,
)


@dataclass(slots=True)
class OpenAIEmailTriageClient:
    api_key: str
    api_base_url: str = settings.OPENAI_API_BASE_URL
    model: str = settings.OPENAI_EMAIL_TRIAGE_MODEL

    def classify_messages(
        self,
        messages: list[GmailMessageRead],
        payload: ConnectedGmailTriageRequest,
    ) -> list[dict[str, str]]:
        if not messages:
            return []

        response = self._request(
            "/responses",
            {
                "model": self.model,
                "store": False,
                "input": _build_classification_prompt(messages, payload),
            },
        )
        text = _extract_response_text(response)
        return _apply_deterministic_overrides(
            messages,
            _parse_classifications(text),
            payload,
        )

    def _request(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self.api_base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OpenAI triage request failed: {_read_error_detail(exc)}",
            ) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="OpenAI triage request could not be completed.",
            ) from exc


def create_email_triage_client() -> OpenAIEmailTriageClient:
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OPENAI_API_KEY is not configured.",
        )

    return OpenAIEmailTriageClient(api_key=settings.OPENAI_API_KEY)


def _build_classification_prompt(
    messages: list[GmailMessageRead],
    payload: ConnectedGmailTriageRequest,
) -> str:
    message_data = [
        {
            "gmail_id": message.gmail_id,
            "category": message.category,
            "subject": message.subject,
            "sender": message.sender,
            "received_at": message.received_at,
            "snippet": message.snippet,
            "body_content": message.body_content,
        }
        for message in messages
    ]

    return f"""
You are an email priority classifier. Classify each Gmail message into exactly
one priority: high, medium, or low.

Priority rules:
- high: needs immediate attention, is very important, has a deadline or
  specific time within the next 1-2 days, contains a clear action item, or
  involves legal, finance, security, customer/user issues, or a direct human
  request.
- medium: relevant but can wait until a later stage, usually 3-4 days or later,
  or is a useful update/follow-up without immediate urgency.
- low: not important, promotional, automated noise, FYI with no action,
  duplicates, or low relevance.

Follow-up rules:
- Follow-up emails are not automatically high priority.
- high: follow-up includes a direct ask, blocked work, missed response, or a
  deadline within 1-2 days.
- medium: follow-up is relevant but can wait, has no near deadline, or asks for
  a non-urgent response.
- low: generic checking-in, networking nudges, sales follow-ups, automated
  reminders, or follow-ups with no clear action item.

Category weighting:
- Primary can be high, medium, or low.
- Updates default to medium. Upgrade to high only when they contain urgent
  action items, near deadlines, legal/finance/security issues, or specific
  dates/times. Downgrade to low when they are noisy or irrelevant.
- Promotions default to low, but can be upgraded:
  - high: urgent deadline today/tomorrow, payment/account/security/legal issue,
    important sender, or a time-sensitive item matching user focus.
  - medium: relevant offer, event, opportunity, course, product update, or
    deadline in 3-7 days that matches user focus but is not urgent.
  - low: generic ad, broad marketing, irrelevant newsletter, or routine alert.

Decision inputs:
- Use subject, sender, received time, Gmail category, snippets/full body content,
  action items, specific dates/times, and deadline proximity.

Hard low-priority examples:
- Job alerts, job recommendations, saved search alerts, newsletter digests,
  promotional deals, marketing campaigns, LinkedIn connection invitations, and
  automated alerts are low unless the user focus explicitly asks to prioritize
  that exact category.
- LinkedIn Job Alerts are low by default.
- LinkedIn connection requests/invitations are low by default.
- Newsletters, digests, social notifications, receipts, shipping updates,
  webinar/event marketing, product announcements, and no-reply notifications
  are low unless they contain account/payment/security/legal risk, a real
  deadline, or a user-focus match.
- Calendar/event invitations for meetings that already happened are low unless
  the message clearly contains a follow-up action item that is still relevant.

Be selective:
- Most emails are low. Do not mark something high just because it is from a
  person, contains polite language, or says "follow up".
- Use high sparingly for items that would cause a problem if ignored today.

User focus:
{payload.user_focus}

Current date:
{datetime.now(UTC).date().isoformat()}

Messages:
{json.dumps(message_data, indent=2)}

Return ONLY valid JSON with this exact shape:
{{
  "classifications": [
    {{
      "gmail_id": "message id from input",
      "priority": "high|medium|low",
      "reason": "short reason"
    }}
  ]
}}
""".strip()


def build_triage_report(
    messages: list[GmailMessageRead],
    classifications: list[dict[str, str]],
    dry_run: bool,
) -> str:
    messages_by_id = {message.gmail_id: message for message in messages}
    counts = {"high": 0, "medium": 0, "low": 0}
    lines = [
        "Dry run: proposed labels only." if dry_run else "Labels applied in Gmail.",
        "",
        "Counts:",
    ]

    for classification in classifications:
        priority = classification["priority"]
        counts[priority] += 1

    lines.extend(
        [
            f"- High: {counts['high']}",
            f"- Medium: {counts['medium']}",
            f"- Low: {counts['low']}",
            "",
            "Classifications:",
        ]
    )

    priority_order = {"high": 0, "medium": 1, "low": 2}
    for classification in sorted(
        classifications,
        key=lambda item: priority_order[item["priority"]],
    ):
        message = messages_by_id.get(classification["gmail_id"])
        if not message:
            continue

        lines.extend(
            [
                f"- {classification['priority'].upper()}: {message.subject or '(no subject)'}",
                f"  From: {message.sender or 'unknown'}",
                f"  Time: {message.received_at or 'unknown'}",
                f"  Category: {message.category}",
                f"  Reason: {classification['reason']}",
            ]
        )

    return "\n".join(lines)


def classifications_to_priority_map(
    classifications: list[dict[str, str]],
) -> dict[str, EmailPriority]:
    return {
        classification["gmail_id"]: EmailPriority(classification["priority"])
        for classification in classifications
    }


def _apply_deterministic_overrides(
    messages: list[GmailMessageRead],
    classifications: list[dict[str, str]],
    payload: ConnectedGmailTriageRequest,
) -> list[dict[str, str]]:
    messages_by_id = {message.gmail_id: message for message in messages}
    focus = payload.user_focus.lower()
    prioritize_jobs = any(
        term in focus
        for term in ["job search", "jobs", "hiring", "recruiter", "career"]
    )
    prioritize_networking = any(
        term in focus
        for term in ["networking", "linkedin", "connections", "partnerships"]
    )

    for classification in classifications:
        message = messages_by_id.get(classification["gmail_id"])
        if not message:
            continue

        subject = (message.subject or "").lower()
        sender = (message.sender or "").lower()
        snippet = (message.snippet or "").lower()
        body_content = (message.body_content or "").lower()
        combined = " ".join([subject, sender, snippet, body_content])

        if _looks_like_past_calendar_event(combined) and not _has_action_or_deadline(
            combined
        ):
            classification["priority"] = "low"
            classification["reason"] = (
                "Calendar event already happened and no current action is evident."
            )
        elif _looks_like_linkedin_connection_request(combined) and not prioritize_networking:
            classification["priority"] = "low"
            classification["reason"] = (
                "LinkedIn connection invitation; low unless networking is the active focus."
            )
        elif _looks_like_job_alert(combined) and not prioritize_jobs:
            classification["priority"] = "low"
            classification["reason"] = (
                "Automated job alert; low unless job search is the active focus."
            )
        elif _looks_like_low_value_automated_email(
            combined
        ) and not _has_important_exception(combined):
            classification["priority"] = "low"
            classification["reason"] = (
                "Automated or broadcast email without urgent account, payment, "
                "security, legal, deadline, or user-focus signal."
            )
        elif (
            classification["priority"] == "high"
            and _looks_like_generic_follow_up(combined)
            and not _has_action_or_deadline(combined)
        ):
            classification["priority"] = "medium"
            classification["reason"] = (
                "Generic follow-up without near deadline or clear blocking action."
            )

    return classifications


def _looks_like_job_alert(text: str) -> bool:
    return any(
        phrase in text
        for phrase in [
            "linkedin job alerts",
            "job alert",
            "jobs matching",
            "posted on",
            "developer (remote)",
            "new jobs",
            "job recommendations",
            "quik hire staffing",
        ]
    )


def _looks_like_linkedin_connection_request(text: str) -> bool:
    return "invitations@linkedin.com" in text or any(
        phrase in text
        for phrase in [
            "wants to connect",
            "i want to connect",
            "invitation to connect",
            "connection request",
            "accept invitation",
        ]
    )


def _looks_like_past_calendar_event(text: str) -> bool:
    if not any(
        phrase in text
        for phrase in [
            "updated invitation:",
            "accepted invitation:",
            "declined invitation:",
            "calendar invitation",
        ]
    ):
        return False

    event_date = _extract_event_date(text)
    if not event_date:
        return False

    return event_date.date() < datetime.now(UTC).date()


def _looks_like_generic_follow_up(text: str) -> bool:
    return any(
        phrase in text
        for phrase in [
            "just following up",
            "checking in",
            "gentle reminder",
            "wanted to follow up",
            "circling back",
            "bumping this",
            "following up on my previous",
        ]
    )


def _looks_like_low_value_automated_email(text: str) -> bool:
    automated_sender = any(
        phrase in text
        for phrase in [
            "noreply@",
            "no-reply@",
            "donotreply@",
            "do-not-reply@",
            "notifications@",
            "newsletter@",
            "digest",
            "unsubscribe",
            "view in browser",
        ]
    )
    automated_content = any(
        phrase in text
        for phrase in [
            "weekly roundup",
            "daily digest",
            "newsletter",
            "new post",
            "someone viewed your profile",
            "people are talking about",
            "webinar",
            "limited time offer",
            "sale ends",
            "recommended for you",
            "order shipped",
            "delivered",
            "receipt",
            "invoice paid",
            "your statement is ready",
        ]
    )
    return automated_sender or automated_content


def _has_important_exception(text: str) -> bool:
    return any(
        phrase in text
        for phrase in [
            "action required",
            "payment failed",
            "past due",
            "overdue",
            "security alert",
            "sign-in attempt",
            "password",
            "legal notice",
            "compliance",
            "invoice due",
            "account suspended",
            "deadline",
            "expires today",
            "expires tomorrow",
            "due today",
            "due tomorrow",
        ]
    )


def _has_action_or_deadline(text: str) -> bool:
    return any(
        phrase in text
        for phrase in [
            "please review",
            "please confirm",
            "please send",
            "please approve",
            "action required",
            "need your",
            "waiting on you",
            "blocked",
            "deadline",
            "due today",
            "due tomorrow",
            "by tomorrow",
            "by eod",
            "asap",
            "urgent",
        ]
    )


def _extract_event_date(text: str) -> datetime | None:
    match = re.search(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
        r"[a-z]*\s+(\d{1,2}),\s+(\d{4})\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    month_lookup = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "sept": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    month = month_lookup[match.group(1)[:3].lower()]
    return datetime(int(match.group(3)), month, int(match.group(2)), tzinfo=UTC)


def _extract_response_text(response: dict[str, Any]) -> str:
    if response.get("output_text"):
        return response["output_text"]

    output_chunks: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                output_chunks.append(text)

    return "\n".join(output_chunks) or json.dumps(response)


def _parse_classifications(text: str) -> list[dict[str, str]]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OpenAI triage response was not valid JSON.",
        ) from exc

    classifications = parsed.get("classifications")
    if not isinstance(classifications, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OpenAI triage response did not include classifications.",
        )

    cleaned: list[dict[str, str]] = []
    for item in classifications:
        priority = item.get("priority")
        if priority not in {"high", "medium", "low"}:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="OpenAI triage response included an invalid priority.",
            )
        cleaned.append(
            {
                "gmail_id": item["gmail_id"],
                "priority": priority,
                "reason": item.get("reason", ""),
            }
        )
    return cleaned


def _read_error_detail(exc: HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode("utf-8"))
        error = body.get("error", {})
        return error.get("message") or exc.reason
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return exc.reason
