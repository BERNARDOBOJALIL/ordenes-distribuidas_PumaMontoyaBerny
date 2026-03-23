"""
Email notification via EmailJS REST API.
"""

import logging
from datetime import datetime, timezone

import httpx

from ..config import settings

logger = logging.getLogger("notifications-service")

EMAILJS_URL = "https://api.emailjs.com/api/v1.0/email/send"


def build_items_html(items: list[dict]) -> str:
    """Build HTML table rows for the email template."""
    if not items:
        return '<tr><td colspan="2" style="padding:10px 12px;text-align:center;color:#888;">Sin productos</td></tr>'
    rows = []
    for item in items:
        rows.append(
            f'<tr>'
            f'<td style="padding:10px 12px;border:1px solid #e5e7eb;">{item.get("sku", "N/A")}</td>'
            f'<td style="padding:10px 12px;text-align:center;border:1px solid #e5e7eb;">{item.get("qty", 0)}</td>'
            f'</tr>'
        )
    return "\n".join(rows)


async def send_email_notification(
    order_id: str,
    customer: str,
    event_type: str,
    message: str,
    items: list[dict] | None = None,
) -> None:
    """
    Send an email notification through the EmailJS REST API.
    Skips silently if EmailJS is not configured (service_id empty).
    """
    if not settings.emailjs_service_id:
        logger.info("[EmailJS] Service ID not configured — skipping email.")
        return

    items = items or []
    items_html = build_items_html(items)
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    payload = {
        "service_id": settings.emailjs_service_id,
        "template_id": settings.emailjs_template_id,
        "user_id": settings.emailjs_public_key,
        "accessToken": settings.emailjs_private_key,
        "template_params": {
            "to_email": settings.notification_to_email,
            "customer_name": customer,
            "order_id": order_id,
            "event_type": event_type,
            "message": message,
            "created_at": now,
            "items_count": str(len(items)),
            "items_html": items_html,
        },
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(EMAILJS_URL, json=payload, timeout=10.0)

    if resp.status_code == 200:
        logger.info("[EmailJS] ✓ Email sent for order_id=%s", order_id)
    else:
        logger.warning(
            "[EmailJS] ✗ Failed (%s): %s",
            resp.status_code,
            resp.text[:200],
        )
        raise RuntimeError(f"EmailJS returned {resp.status_code}: {resp.text[:200]}")
