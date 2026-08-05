"""Per-resource behavior, and proof that every async twin matches its sync sibling."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from postify import OPERATIONS, AsyncPostify, Postify

from .conftest import (
    API_KEY,
    BASE_URL,
    analytics,
    channel,
    post,
    usage,
    webhook_endpoint,
)

# --------------------------------------------------------------------------- #
# Webhook endpoints
# --------------------------------------------------------------------------- #


@respx.mock
def test_listing_webhook_endpoints_returns_models(client: Postify) -> None:
    respx.get(f"{BASE_URL}/v1/webhook-endpoints").mock(
        return_value=httpx.Response(200, json={"data": [webhook_endpoint()]})
    )
    endpoints = client.webhook_endpoints.list()
    assert endpoints[0].id == "whe_1"
    assert endpoints[0].event_types == ["post.published", "post.failed"]
    assert endpoints[0].consecutive_failures == 0


@respx.mock
def test_creating_an_endpoint_surfaces_the_show_once_signing_secret(
    client: Postify,
) -> None:
    route = respx.post(f"{BASE_URL}/v1/webhook-endpoints").mock(
        return_value=httpx.Response(
            201, json=dict(webhook_endpoint(), signing_secret="whsec_showedonce")
        )
    )
    created = client.webhook_endpoints.create(
        url="https://api.example.com/hooks", event_types=["post.published"]
    )
    assert created.signing_secret == "whsec_showedonce"
    assert json.loads(route.calls[0].request.content) == {
        "url": "https://api.example.com/hooks",
        "event_types": ["post.published"],
    }


@respx.mock
def test_updating_an_endpoint_sends_only_the_mentioned_fields(client: Postify) -> None:
    route = respx.patch(f"{BASE_URL}/v1/webhook-endpoints/whe_1").mock(
        return_value=httpx.Response(200, json=webhook_endpoint(enabled=False))
    )
    updated = client.webhook_endpoints.update("whe_1", enabled=False)
    assert updated.enabled is False
    assert json.loads(route.calls[0].request.content) == {"enabled": False}


@respx.mock
def test_updating_event_types_normalizes_any_sequence_to_a_list(client: Postify) -> None:
    route = respx.patch(f"{BASE_URL}/v1/webhook-endpoints/whe_1").mock(
        return_value=httpx.Response(200, json=webhook_endpoint())
    )
    client.webhook_endpoints.update("whe_1", event_types=("post.failed",))
    assert json.loads(route.calls[0].request.content) == {"event_types": ["post.failed"]}


def test_an_empty_update_is_rejected_before_a_request_is_made(client: Postify) -> None:
    with pytest.raises(ValueError):
        client.webhook_endpoints.update("whe_1")


@respx.mock
def test_deleting_and_testing_an_endpoint(client: Postify) -> None:
    respx.delete(f"{BASE_URL}/v1/webhook-endpoints/whe_1").mock(
        return_value=httpx.Response(200, json={"id": "whe_1", "deleted": True})
    )
    respx.post(f"{BASE_URL}/v1/webhook-endpoints/whe_1/test").mock(
        return_value=httpx.Response(
            200,
            json={"delivery_id": "dlv_1", "succeeded": True, "http_code": 200, "error": None},
        )
    )
    assert client.webhook_endpoints.delete("whe_1").deleted is True
    result = client.webhook_endpoints.test("whe_1")
    assert result.succeeded is True
    assert result.http_code == 200


@respx.mock
def test_a_failed_test_delivery_reports_the_transport_error(client: Postify) -> None:
    respx.post(f"{BASE_URL}/v1/webhook-endpoints/whe_1/test").mock(
        return_value=httpx.Response(
            200,
            json={
                "delivery_id": "dlv_2",
                "succeeded": False,
                "http_code": None,
                "error": "connect ETIMEDOUT",
            },
        )
    )
    result = client.webhook_endpoints.test("whe_1")
    assert result.succeeded is False
    assert result.http_code is None
    assert result.error == "connect ETIMEDOUT"


# --------------------------------------------------------------------------- #
# Posts, analytics, usage, channels
# --------------------------------------------------------------------------- #


@respx.mock
def test_publish_accepts_with_202_and_reports_the_new_status(client: Postify) -> None:
    respx.post(f"{BASE_URL}/v1/posts/pst_1/publish").mock(
        return_value=httpx.Response(202, json={"id": "pst_1", "status": "publishing"})
    )
    accepted = client.posts.publish("pst_1")
    assert accepted.status == "publishing"


@respx.mock
def test_a_post_exposes_its_variants_and_deliveries(client: Postify) -> None:
    respx.get(f"{BASE_URL}/v1/posts/pst_1").mock(
        return_value=httpx.Response(
            200,
            json=post(
                status="published",
                deliveries=[
                    {
                        "channel_id": "chn_1",
                        "stage": "indexed",
                        "external_id": "urn:li:share:1",
                        "error": None,
                    },
                    {
                        "channel_id": "chn_2",
                        "stage": "failed",
                        "external_id": None,
                        "error": "token expired",
                    },
                ],
            ),
        )
    )
    fetched = client.posts.get("pst_1")
    assert fetched.status == "published"
    # A published post can still contain failed channels — partial delivery.
    assert [d.stage for d in fetched.deliveries] == ["indexed", "failed"]
    assert fetched.variants[0].channel_id == "chn_1"


@respx.mock
def test_analytics_and_usage_parse_their_nested_shapes(client: Postify) -> None:
    respx.get(f"{BASE_URL}/v1/analytics").mock(return_value=httpx.Response(200, json=analytics()))
    respx.get(f"{BASE_URL}/v1/usage").mock(return_value=httpx.Response(200, json=usage()))
    stats = client.analytics.get()
    assert stats.totals.published == 30
    assert stats.delivery.success_rate == 0.93
    assert stats.timeline[0].date == "2026-08-04"
    assert stats.engagement.impressions == 15000

    plan = client.usage.get()
    assert plan.plan == "team"
    assert plan.meter("api_requests").remaining == 9588


@respx.mock
def test_an_injected_http_client_is_used_and_never_closed_by_the_sdk() -> None:
    respx.get(f"{BASE_URL}/v1/channels").mock(
        return_value=httpx.Response(200, json={"data": [channel()]})
    )
    injected = httpx.Client()
    with Postify(api_key=API_KEY, base_url=BASE_URL, http_client=injected) as client:
        assert client.channels.list()[0].id == "chn_1"
    assert not injected.is_closed
    injected.close()


@respx.mock
def test_a_trailing_slash_on_the_base_url_does_not_double_up(client: Postify) -> None:
    route = respx.get(f"{BASE_URL}/v1/channels").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    with Postify(api_key=API_KEY, base_url=f"{BASE_URL}/") as trailing:
        trailing.channels.list()
    assert str(route.calls[0].request.url) == f"{BASE_URL}/v1/channels"


# --------------------------------------------------------------------------- #
# Async parity
# --------------------------------------------------------------------------- #


@respx.mock
async def test_every_async_resource_method_reaches_the_same_endpoint() -> None:
    respx.get(f"{BASE_URL}/v1/channels").mock(
        return_value=httpx.Response(200, json={"data": [channel()]})
    )
    respx.get(f"{BASE_URL}/v1/analytics").mock(return_value=httpx.Response(200, json=analytics()))
    respx.get(f"{BASE_URL}/v1/usage").mock(return_value=httpx.Response(200, json=usage()))
    respx.get(f"{BASE_URL}/v1/posts/pst_1").mock(return_value=httpx.Response(200, json=post()))
    respx.patch(f"{BASE_URL}/v1/posts/pst_1").mock(return_value=httpx.Response(200, json=post()))
    respx.delete(f"{BASE_URL}/v1/posts/pst_1").mock(
        return_value=httpx.Response(200, json={"id": "pst_1", "deleted": True})
    )
    respx.post(f"{BASE_URL}/v1/posts/pst_1/publish").mock(
        return_value=httpx.Response(202, json={"id": "pst_1", "status": "publishing"})
    )
    respx.get(f"{BASE_URL}/v1/webhook-endpoints").mock(
        return_value=httpx.Response(200, json={"data": [webhook_endpoint()]})
    )
    respx.post(f"{BASE_URL}/v1/webhook-endpoints").mock(
        return_value=httpx.Response(
            201, json=dict(webhook_endpoint(), signing_secret="whsec_async")
        )
    )
    respx.patch(f"{BASE_URL}/v1/webhook-endpoints/whe_1").mock(
        return_value=httpx.Response(200, json=webhook_endpoint(enabled=False))
    )
    respx.delete(f"{BASE_URL}/v1/webhook-endpoints/whe_1").mock(
        return_value=httpx.Response(200, json={"id": "whe_1", "deleted": True})
    )
    respx.post(f"{BASE_URL}/v1/webhook-endpoints/whe_1/test").mock(
        return_value=httpx.Response(
            200,
            json={"delivery_id": "dlv_1", "succeeded": True, "http_code": 200, "error": None},
        )
    )

    async with AsyncPostify(api_key=API_KEY, base_url=BASE_URL) as client:
        assert (await client.channels.list())[0].id == "chn_1"
        assert (await client.analytics.get()).totals.posts == 42
        assert (await client.usage.get()).plan == "team"
        assert (await client.posts.get("pst_1")).id == "pst_1"
        assert (
            await client.posts.reschedule("pst_1", scheduled_at="2026-10-01T09:00:00Z")
        ).id == "pst_1"
        assert (await client.posts.delete("pst_1")).deleted is True
        assert (await client.posts.publish("pst_1")).status == "publishing"
        assert (await client.webhook_endpoints.list())[0].id == "whe_1"
        created = await client.webhook_endpoints.create(
            url="https://api.example.com/hooks", event_types=["post.published"]
        )
        assert created.signing_secret == "whsec_async"
        assert (await client.webhook_endpoints.update("whe_1", enabled=False)).enabled is False
        assert (await client.webhook_endpoints.delete("whe_1")).deleted is True
        assert (await client.webhook_endpoints.test("whe_1")).succeeded is True


async def test_the_async_client_closes_cleanly_and_reports_itself_safely() -> None:
    client = AsyncPostify(api_key=API_KEY, base_url=BASE_URL)
    assert API_KEY not in repr(client)
    await client.aclose()


def test_sync_and_async_expose_the_same_resource_method_names() -> None:
    sync_client = Postify(api_key=API_KEY, base_url=BASE_URL)
    async_client = AsyncPostify(api_key=API_KEY, base_url=BASE_URL)
    try:
        for op in OPERATIONS:
            sync_method = getattr(getattr(sync_client, op.resource), op.method_name)
            async_method = getattr(getattr(async_client, op.resource), op.method_name)
            assert sync_method.__name__ == async_method.__name__
        # The Python-only upload convenience exists on both faces too.
        assert callable(sync_client.media.upload)
        assert callable(async_client.media.upload)
    finally:
        sync_client.close()
