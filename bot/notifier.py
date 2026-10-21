"""
Optional Discord webhook notifications.
"""
import logging
import traceback

import httpx

logger = logging.getLogger(__name__)

GREEN = 0x2ECC71
RED = 0xE74C3C
GREY = 0x95A5A6
ORANGE = 0xE67E22

# Discord embed description limit
_MAX_DESC = 4000


def send_discord(webhook_url: str, title: str, body: str, color: int = GREY) -> bool:
    """Post an embed to a Discord webhook. Returns True if it was delivered."""
    if not webhook_url:
        return False

    payload = {
        "embeds": [{
            "title": f"[tqqq-bot] {title}"[:256],
            "description": body[-_MAX_DESC:],
            "color": color,
        }]
    }
    try:
        resp = httpx.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Discord notification sent: %s", title)
        return True
    except Exception as exc:
        # Don't log the URL — it contains the webhook token
        logger.warning("Failed to send Discord notification: %s", type(exc).__name__)
        return False


def send_failure(webhook_url: str, exc: Exception, title: str = "Run FAILED") -> bool:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    # Keep the tail of the traceback — that's where the actual error is
    return send_discord(webhook_url, title, f"```\n{tb[-(_MAX_DESC - 10):]}\n```", RED)
