"""Idempotency-Key generation, passthrough, opt-out and replay surfacing."""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from postify import (
    APIConnectionError,
    AsyncPostify,
    ConflictError,
    Postify,
    UnprocessableEntityError,
)

from .conftest import API_KEY, BASE_URL, post, problem


@respx.mock
def test_posts_create_generates_a_uuid_idempotency_key_by_default(
    client: Postify,
) -> None:
    route = respx.post(f"{BASE_URL}/v1/posts").mock(return_value=httpx.Response(201, json=post()))
    client.posts.create(variants=[{"channel_id": "chn_1", "body": "hi"}], draft=True)
    sent = route.calls[0].request.headers["idempotency-key"]
    assert uuid.UUID(sent).version == 4


@respx.mock
def test_two_creates_get_two_different_generated_keys(client: Postify) -> None:
    route = respx.post(f"{BASE_URL}/v1/posts").mock(return_value=httpx.Response(201, json=post()))
    client.posts.create(variants=[{"channel_id": "chn_1", "body": "a"}], draft=True)
    client.posts.create(variants=[{"channel_id": "chn_1", "body": "b"}], draft=True)
    keys = [call.request.headers["idempotency-key"] for call in route.calls]
    assert keys[0] != keys[1]


@respx.mock
def test_an_explicit_key_is_passed_through_verbatim(client: Postify) -> None:
    route = respx.post(f"{BASE_URL}/v1/posts").mock(return_value=httpx.Response(201, json=post()))
    client.posts.create(
        variants=[{"channel_id": "chn_1", "body": "hi"}],
        draft=True,
        idempotency_key="order-42-post",
    )
    assert route.calls[0].request.headers["idempotency-key"] == "order-42-post"


@respx.mock
def test_idempotency_key_false_omits_the_header_entirely(client: Postify) -> None:
    route = respx.post(f"{BASE_URL}/v1/posts").mock(return_value=httpx.Response(201, json=post()))
    client.posts.create(
        variants=[{"channel_id": "chn_1", "body": "hi"}], draft=True, idempotency_key=False
    )
    assert "idempotency-key" not in route.calls[0].request.headers


@respx.mock
def test_an_unkeyed_create_is_therefore_not_retried(client: Postify) -> None:
    route = respx.post(f"{BASE_URL}/v1/posts").mock(side_effect=httpx.ConnectError("reset"))
    with pytest.raises(APIConnectionError):
        client.posts.create(
            variants=[{"channel_id": "chn_1", "body": "hi"}],
            draft=True,
            idempotency_key=False,
        )
    assert route.call_count == 1


@respx.mock
def test_the_replay_header_is_surfaced_on_the_returned_model(client: Postify) -> None:
    respx.post(f"{BASE_URL}/v1/posts").mock(
        return_value=httpx.Response(
            201,
            json=post(),
            headers={"Idempotency-Replayed": "true", "Request-Id": "req_replay"},
        )
    )
    created = client.posts.create(variants=[{"channel_id": "chn_1", "body": "hi"}], draft=True)
    assert created.idempotency_replayed is True
    assert created.request_id == "req_replay"


@respx.mock
def test_a_first_time_create_is_not_flagged_as_replayed(client: Postify) -> None:
    respx.post(f"{BASE_URL}/v1/posts").mock(return_value=httpx.Response(201, json=post()))
    created = client.posts.create(variants=[{"channel_id": "chn_1", "body": "hi"}], draft=True)
    assert created.idempotency_replayed is False


@respx.mock
def test_reusing_a_key_with_a_different_body_raises_unprocessable_entity(
    client: Postify,
) -> None:
    respx.post(f"{BASE_URL}/v1/posts").mock(
        return_value=httpx.Response(422, json=problem(422, "idempotency_key_reused"))
    )
    with pytest.raises(UnprocessableEntityError) as excinfo:
        client.posts.create(
            variants=[{"channel_id": "chn_1", "body": "changed"}],
            draft=True,
            idempotency_key="order-42-post",
        )
    assert excinfo.value.code == "idempotency_key_reused"


@respx.mock
def test_an_in_flight_original_eventually_raises_conflict(client: Postify) -> None:
    respx.post(f"{BASE_URL}/v1/posts").mock(
        return_value=httpx.Response(
            409, json=problem(409, "idempotency_in_progress"), headers={"Retry-After": "2"}
        )
    )
    with pytest.raises(ConflictError) as excinfo:
        client.posts.create(
            variants=[{"channel_id": "chn_1", "body": "hi"}],
            draft=True,
            idempotency_key="order-42-post",
        )
    assert excinfo.value.code == "idempotency_in_progress"


@respx.mock
def test_no_other_operation_sends_an_idempotency_key(client: Postify) -> None:
    patch = respx.patch(f"{BASE_URL}/v1/posts/pst_1").mock(
        return_value=httpx.Response(200, json=post())
    )
    delete = respx.delete(f"{BASE_URL}/v1/posts/pst_1").mock(
        return_value=httpx.Response(200, json={"id": "pst_1", "deleted": True})
    )
    publish = respx.post(f"{BASE_URL}/v1/posts/pst_1/publish").mock(
        return_value=httpx.Response(202, json={"id": "pst_1", "status": "publishing"})
    )
    client.posts.reschedule("pst_1", scheduled_at="2026-10-01T09:00:00Z")
    client.posts.delete("pst_1")
    client.posts.publish("pst_1")
    for route in (patch, delete, publish):
        assert "idempotency-key" not in route.calls[0].request.headers


@respx.mock
def test_patch_bodies_carry_only_the_field_that_changed(client: Postify) -> None:
    route = respx.patch(f"{BASE_URL}/v1/posts/pst_1").mock(
        return_value=httpx.Response(200, json=post())
    )
    client.posts.reschedule("pst_1", scheduled_at="2026-10-01T09:00:00Z")
    import json

    assert json.loads(route.calls[0].request.content) == {"scheduled_at": "2026-10-01T09:00:00Z"}


@respx.mock
def test_create_bodies_omit_every_argument_the_caller_left_alone(client: Postify) -> None:
    route = respx.post(f"{BASE_URL}/v1/posts").mock(return_value=httpx.Response(201, json=post()))
    client.posts.create(variants=[{"channel_id": "chn_1", "body": "hi"}], draft=True)
    import json

    body = json.loads(route.calls[0].request.content)
    assert body == {"variants": [{"channel_id": "chn_1", "body": "hi"}], "draft": True}


@respx.mock
def test_an_explicit_null_title_is_sent_while_an_unmentioned_one_is_not(
    client: Postify,
) -> None:
    route = respx.post(f"{BASE_URL}/v1/posts").mock(return_value=httpx.Response(201, json=post()))
    client.posts.create(variants=[{"channel_id": "chn_1", "body": "hi"}], draft=True, title=None)
    import json

    assert json.loads(route.calls[0].request.content)["title"] is None


@respx.mock
async def test_the_async_create_generates_a_key_too() -> None:
    route = respx.post(f"{BASE_URL}/v1/posts").mock(return_value=httpx.Response(201, json=post()))
    async with AsyncPostify(api_key=API_KEY, base_url=BASE_URL) as client:
        await client.posts.create(variants=[{"channel_id": "chn_1", "body": "hi"}], draft=True)
    assert uuid.UUID(route.calls[0].request.headers["idempotency-key"]).version == 4
