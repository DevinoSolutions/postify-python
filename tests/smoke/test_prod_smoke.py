"""Production smoke checks against https://app.usepostify.com.

Run before every release: ``pytest tests/smoke -v`` (or the ``Smoke`` workflow).

Safety rules baked in:

* Every post created here is a **draft**. ``publish_now`` and ``posts.publish``
  post to real social accounts and are gated behind
  ``POSTIFY_SMOKE_ALLOW_PUBLISH=1``; they are excluded from the default run.
* Everything created is deleted in teardown.
* Missing credentials skip loudly — they never fail the suite.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import httpx
import pytest

from postify import (
    AuthenticationError,
    PermissionDeniedError,
    Postify,
    UnprocessableEntityError,
)

from .conftest import PROD_BASE_URL

pytestmark = pytest.mark.smoke

SPEC_PATH = Path(__file__).resolve().parents[2] / "spec" / "v1.json"

# A 1x1 transparent PNG.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4949484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd40000"
    "000049454e44ae426082"
)


def test_1_the_public_spec_endpoint_matches_the_vendored_fixture() -> None:
    """A mismatch means the SDK is stale against production."""
    response = httpx.get(f"{PROD_BASE_URL}/v1/openapi.json", timeout=30)
    assert response.status_code == 200
    live = response.json()
    assert live["info"]["version"]
    vendored = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    assert live == vendored, "spec/v1.json is stale — run ./scripts/sync-spec.sh"


def test_2_usage_reports_the_api_requests_meter_and_rate_limit_headers(
    client: Postify,
) -> None:
    usage = client.usage.get()
    assert usage.plan
    assert usage.meter("api_requests") is not None
    state = client.last_rate_limit
    assert state is not None, "no rate-limit headers observed on an API-key response"
    assert state.limit is not None


def test_3_channels_list_returns_and_carries_a_request_id(client: Postify) -> None:
    channels = client.channels.list()
    assert isinstance(channels, list)
    assert client.last_request_id, "every /v1 response must carry Request-Id"


def test_4_posts_list_paginates_with_a_real_cursor(client: Postify) -> None:
    page = client.posts.list(limit=1).first_page()
    assert isinstance(page.has_more, bool)
    if page.has_more:
        assert page.next_cursor
        second = page.get_next_page()
        assert second is not None
        first_ids = {post.id for post in page.data}
        assert first_ids.isdisjoint({post.id for post in second.data})


def test_5_analytics_returns_a_summary(client: Postify) -> None:
    analytics = client.analytics.get()
    assert analytics.totals.posts >= 0
    assert isinstance(analytics.timeline, list)


def test_6_a_bad_key_is_rejected_with_invalid_api_key(monkeypatch) -> None:
    with (
        Postify(
            api_key="postify_live_definitelynotarealkey", base_url=PROD_BASE_URL, max_retries=0
        ) as client,
        pytest.raises(AuthenticationError) as excinfo,
    ):
        client.channels.list()
    assert excinfo.value.code in ("invalid_api_key", "authentication_required")
    assert excinfo.value.headers.get("www-authenticate", "").lower().startswith("bearer")


def test_7_a_read_only_key_cannot_create_posts(readonly_api_key: str) -> None:
    with Postify(api_key=readonly_api_key, base_url=PROD_BASE_URL, max_retries=0) as client:
        with pytest.raises(PermissionDeniedError) as excinfo:
            client.posts.create(
                variants=[{"channel_id": "chn_smoke", "body": "scope probe"}], draft=True
            )
    assert excinfo.value.code == "insufficient_scope"


def test_8_an_idempotent_create_replays_and_rejects_a_changed_body(
    client: Postify, created_post_ids: list[str]
) -> None:
    channels = [c for c in client.channels.list() if c.status == "live"]
    if not channels:
        pytest.skip("SKIPPED: the smoke workspace has no live channel to target.")

    key = f"smoke-{uuid.uuid4()}"
    body = {
        "variants": [{"channel_id": channels[0].id, "body": "postify-python smoke draft"}],
        "draft": True,
    }

    first = client.posts.create(idempotency_key=key, **body)
    created_post_ids.append(first.id)
    assert first.idempotency_replayed is False

    replay = client.posts.create(idempotency_key=key, **body)
    assert replay.id == first.id
    assert replay.idempotency_replayed is True

    with pytest.raises(UnprocessableEntityError) as excinfo:
        client.posts.create(
            idempotency_key=key,
            variants=[{"channel_id": channels[0].id, "body": "a different body"}],
            draft=True,
        )
    assert excinfo.value.code == "idempotency_key_reused"


def test_9_a_media_round_trip_lands_in_the_library(client: Postify) -> None:
    asset = client.media.upload(TINY_PNG, filename=f"smoke-{uuid.uuid4().hex}.png")
    assert asset.id
    listed = {item.id for item in client.media.list(limit=25)}
    assert asset.id in listed


@pytest.mark.skipif(
    os.environ.get("POSTIFY_SMOKE_ALLOW_PUBLISH") != "1",
    reason="publishing posts to real social accounts requires POSTIFY_SMOKE_ALLOW_PUBLISH=1",
)
def test_10_publishing_is_gated_behind_the_dangerous_ops_toggle(client: Postify) -> None:
    channels = [c for c in client.channels.list() if c.status == "live"]
    if not channels:
        pytest.skip("SKIPPED: the smoke workspace has no live channel to target.")
    with pytest.raises(PermissionDeniedError) as excinfo:
        client.posts.create(
            variants=[{"channel_id": channels[0].id, "body": "smoke publish probe"}],
            publish_now=True,
        )
    assert excinfo.value.code == "dangerous_ops_disabled"
