"""plex.tv helpers: PIN based sign-in and server discovery."""
from urllib.parse import urlencode

import httpx

from . import config

PLEX_TV = "https://plex.tv/api/v2"


def _headers(client_id: str, token: str | None = None) -> dict:
    headers = {
        "Accept": "application/json",
        "X-Plex-Product": config.APP_NAME,
        "X-Plex-Version": config.VERSION,
        "X-Plex-Client-Identifier": client_id,
    }
    if token:
        headers["X-Plex-Token"] = token
    return headers


def create_pin(client_id: str) -> dict:
    resp = httpx.post(f"{PLEX_TV}/pins", params={"strong": "true"},
                      headers=_headers(client_id), timeout=20)
    resp.raise_for_status()
    pin = resp.json()
    auth_url = "https://app.plex.tv/auth#?" + urlencode({
        "clientID": client_id,
        "code": pin["code"],
        "context[device][product]": config.APP_NAME,
    })
    return {"id": pin["id"], "code": pin["code"], "auth_url": auth_url}


def check_pin(client_id: str, pin_id: int) -> str | None:
    resp = httpx.get(f"{PLEX_TV}/pins/{pin_id}", headers=_headers(client_id), timeout=20)
    resp.raise_for_status()
    return resp.json().get("authToken") or None


def servers(client_id: str, token: str) -> list[dict]:
    """Plex Media Servers the account can reach, with their connection URLs."""
    resp = httpx.get(f"{PLEX_TV}/resources",
                     params={"includeHttps": 1, "includeRelay": 0},
                     headers=_headers(client_id, token), timeout=20)
    resp.raise_for_status()
    result = []
    for res in resp.json():
        if "server" not in (res.get("provides") or ""):
            continue
        result.append({
            "name": res.get("name"),
            "owned": res.get("owned"),
            "token": res.get("accessToken") or token,
            "connections": [
                {"uri": c.get("uri"), "local": c.get("local"), "relay": c.get("relay")}
                for c in res.get("connections", [])
            ],
        })
    return result
