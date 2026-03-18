import logging

import httpx

from ..config import settings
from ..schemas import OrderCreatedEvent

logger = logging.getLogger("notification-service")

EMAILJS_API_URL = "https://api.emailjs.com/api/v1.0/email/send"


def build_items_html(event: OrderCreatedEvent) -> str:
    rows = ""
    for item in event.items:
        rows += (
            f"<tr>"
            f"<td style='padding:8px 12px;border:1px solid #ddd;'>{item.sku}</td>"
            f"<td style='padding:8px 12px;border:1px solid #ddd;text-align:center;'>{item.qty}</td>"
            f"</tr>"
        )
    return rows


def send_confirmation(event: OrderCreatedEvent) -> None:
    if not settings.emailjs_service_id:
        logger.warning("EmailJS no configurado, se imprime en log.")
        logger.info(
            "[MOCK EMAIL] customer=%s order_id=%s items=%s",
            event.customer, event.order_id, event.items,
        )
        return

    items_html = build_items_html(event)

    template_params = {
        "to_email": settings.notification_to_email,
        "customer_name": event.customer,
        "order_id": event.order_id,
        "created_at": event.created_at or "N/A",
        "items_html": items_html,
        "items_count": str(len(event.items)),
    }

    payload = {
        "service_id":  settings.emailjs_service_id,
        "template_id": settings.emailjs_template_id,
        "user_id":     settings.emailjs_public_key,
        "accessToken": settings.emailjs_private_key,
        "template_params": template_params,
    }

    try:
        resp = httpx.post(EMAILJS_API_URL, json=payload, timeout=10.0)
        if resp.status_code == 200:
            logger.info(
                "email enviado a=%s order_id=%s",
                settings.notification_to_email, event.order_id,
            )
        else:
            logger.error(
                "EmailJS respondió %d: %s",
                resp.status_code, resp.text,
            )
    except Exception as exc:
        logger.error("error enviando email: %s", exc)
