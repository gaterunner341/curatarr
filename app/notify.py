"""Discord (or Discord-compatible) webhook notifications for sync results."""
import logging

import httpx

from . import config

log = logging.getLogger(__name__)

COLORS = {"success": 0x2ECC71, "warning": 0xF1C40F, "error": 0xE74C3C, "skipped": 0x95A5A6}


def should_notify(level: str, run: dict) -> bool:
    if level == "off":
        return False
    if run["status"] == "error":
        return True
    if level == "always":
        return True
    if level == "changes":
        return bool(run.get("added") or run.get("removed") or run.get("requested"))
    return False


def send(webhook: str, title: str, description: str, color: int = COLORS["success"],
         fields: list[tuple[str, str]] | None = None) -> None:
    payload = {
        "username": config.APP_NAME,
        "embeds": [{
            "title": title[:256],
            "description": description[:4000],
            "color": color,
            "fields": [{"name": n, "value": v or "-", "inline": True} for n, v in fields or []],
        }],
    }
    resp = httpx.post(webhook, json=payload, timeout=15)
    resp.raise_for_status()


def notify_run(settings: dict, run: dict) -> None:
    webhook = settings.get("discord_webhook")
    if not webhook or not should_notify(settings.get("notify_level", "changes"), run):
        return
    try:
        send(
            webhook,
            f"{run['collection_name']}: {run['status']}",
            run.get("message") or "",
            COLORS.get(run["status"], COLORS["success"]),
            [("Matched", str(run.get("matched", 0))), ("Added", str(run.get("added", 0))),
             ("Removed", str(run.get("removed", 0))),
             ("Missing", str(len(run.get("missing") or []))),
             ("Requested", str(run.get("requested", 0)))],
        )
    except httpx.HTTPError as exc:
        log.warning("Notification failed: %s", exc)
