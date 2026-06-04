import json
from dataclasses import dataclass
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
            "body_preview": message.body_preview,
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
- Use subject, sender, received time, Gmail category, snippets/body cues,
  action items, specific dates/times, and deadline proximity.

Hard low-priority examples:
- Job alerts, job recommendations, saved search alerts, newsletter digests,
  promotional deals, marketing campaigns, and automated alerts are low unless
  the user focus explicitly asks to prioritize that exact category.
- LinkedIn Job Alerts are low by default.

User focus:
{payload.user_focus}

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

    for classification in classifications:
        message = messages_by_id.get(classification["gmail_id"])
        if not message:
            continue

        subject = (message.subject or "").lower()
        sender = (message.sender or "").lower()
        snippet = (message.snippet or "").lower()
        body_preview = (message.body_preview or "").lower()
        combined = " ".join([subject, sender, snippet, body_preview])

        if _looks_like_job_alert(combined) and not prioritize_jobs:
            classification["priority"] = "low"
            classification["reason"] = (
                "Automated job alert; low unless job search is the active focus."
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
