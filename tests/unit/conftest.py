"""Shared fixtures and canned wire payloads for the offline test suite."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Optional

import pytest

from postify import Postify, errors, problem_type_uri
from postify import _client as client_module

BASE_URL = "https://app.usepostify.com"
API_KEY = "postify_live_examplekey1234"
WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"s" * 24).decode()


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record backoff delays instead of actually sleeping through them."""
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    async def fake_asleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(client_module, "_sleep", fake_sleep)
    monkeypatch.setattr(client_module, "_asleep", fake_asleep)
    return slept


@pytest.fixture
def slept(no_sleeping: list[float]) -> list[float]:
    """Alias so tests can assert on recorded backoff delays by name."""
    return no_sleeping


@pytest.fixture
def client() -> Postify:
    instance = Postify(api_key=API_KEY, base_url=BASE_URL)
    yield instance
    instance.close()


# --------------------------------------------------------------------------- #
# Canned payloads, shaped exactly like the /v1 wire contracts
# --------------------------------------------------------------------------- #


def problem(
    status: int,
    code: str,
    *,
    detail: Optional[str] = None,
    request_id: str = "req_9f2c1e4ab8d64f0e",
    field_errors: Optional[list[dict[str, str]]] = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": problem_type_uri(code),
        "title": errors.PROBLEM_CODES.get(code, {}).get("title", "Error"),
        "status": status,
        "code": code,
        "request_id": request_id,
    }
    if detail is not None:
        body["detail"] = detail
    if field_errors is not None:
        body["errors"] = field_errors
    return body


def channel(channel_id: str = "chn_1", **overrides: Any) -> dict[str, Any]:
    payload = {
        "id": channel_id,
        "platform": "linkedin",
        "handle": "Acme Inc",
        "avatar_url": None,
        "followers": 1200,
        "status": "live",
        "last_sync_at": "2026-08-01T10:00:00.000Z",
        "last_error": None,
        "created_at": "2026-01-04T09:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def post(post_id: str = "pst_1", **overrides: Any) -> dict[str, Any]:
    payload = {
        "id": post_id,
        "status": "scheduled",
        "type": "single",
        "title": None,
        "body": "Shipping the new API today.",
        "scheduled_at": "2026-09-01T15:00:00.000Z",
        "published_at": None,
        "created_at": "2026-08-05T12:00:00.000Z",
        "variants": [
            {
                "id": "var_1",
                "channel_id": "chn_1",
                "body": "Shipping the new API today.",
                "media": [],
            }
        ],
        "deliveries": [],
    }
    payload.update(overrides)
    return payload


def post_page(
    ids: list[str], *, has_more: bool = False, next_cursor: Optional[str] = None
) -> dict[str, Any]:
    return {
        "data": [post(post_id) for post_id in ids],
        "has_more": has_more,
        "next_cursor": next_cursor,
    }


def media_asset(asset_id: str = "ast_1", **overrides: Any) -> dict[str, Any]:
    payload = {
        "id": asset_id,
        "filename": "teaser.png",
        "content_type": "image/png",
        "kind": "image",
        "status": "ready",
        "url": "https://cdn.usepostify.com/media/ast_1.png",
        "size_bytes": 8,
        "width": 1,
        "height": 1,
        "duration_sec": None,
        "created_at": "2026-08-05T12:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def media_page(
    ids: list[str], *, has_more: bool = False, next_cursor: Optional[str] = None
) -> dict[str, Any]:
    return {
        "data": [media_asset(asset_id) for asset_id in ids],
        "has_more": has_more,
        "next_cursor": next_cursor,
    }


def usage() -> dict[str, Any]:
    return {
        "plan": "team",
        "meters": [
            {
                "key": "api_requests",
                "used": 412,
                "limit": 10000,
                "remaining": 9588,
                "period_starts_at": "2026-08-01T00:00:00.000Z",
                "period_ends_at": "2026-09-01T00:00:00.000Z",
            }
        ],
    }


def analytics() -> dict[str, Any]:
    return {
        "totals": {
            "posts": 42,
            "published": 30,
            "scheduled": 8,
            "failed": 4,
            "channels": 3,
        },
        "delivery": {"attempts": 61, "success_rate": 0.93},
        "timeline": [{"date": "2026-08-04", "published": 2}],
        "engagement": {
            "impressions": 15000,
            "likes": 320,
            "comments": 41,
            "shares": 12,
            "clicks": 88,
        },
    }


def webhook_endpoint(endpoint_id: str = "whe_1", **overrides: Any) -> dict[str, Any]:
    payload = {
        "id": endpoint_id,
        "url": "https://api.example.com/postify/webhooks",
        "event_types": ["post.published", "post.failed"],
        "enabled": True,
        "auto_disabled_at": None,
        "consecutive_failures": 0,
        "created_at": "2026-08-05T12:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def upload_ticket(asset_id: str = "ast_1") -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "upload_url": "https://storage.example.com/bucket/ast_1?X-Amz-Signature=deadbeef",
        "method": "PUT",
        "expires_at": "2026-08-05T13:00:00.000Z",
    }


def sign_webhook(
    body: bytes,
    *,
    webhook_id: str = "evt_1",
    timestamp: Optional[int] = None,
    secret: str = WEBHOOK_SECRET,
) -> dict[str, str]:
    """Build the delivery headers exactly as the server's signer does."""
    import time as _time

    ts = str(timestamp if timestamp is not None else int(_time.time()))
    raw = secret[6:] if secret.startswith("whsec_") else secret
    key = base64.b64decode(raw.replace("-", "+").replace("_", "/") + "=" * (-len(raw) % 4))
    signed = webhook_id.encode() + b"." + ts.encode() + b"." + body
    digest = hmac.new(key, signed, hashlib.sha256).digest()
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": ts,
        "webhook-signature": "v1," + base64.b64encode(digest).decode(),
    }


def event_body(event_id: str = "evt_1", event_type: str = "post.published") -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "createdAt": "2026-08-05T12:00:00.000Z",
            "data": {"postId": "pst_1", "succeeded": 1, "failed": 0},
        }
    ).encode()
