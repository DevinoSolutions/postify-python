"""Auth header wiring, User-Agent, and the guarantee that keys never leak into logs."""

from __future__ import annotations

import httpx
import pytest
import respx

from postify import AsyncPostify, Postify, PostifyError, redact_api_key
from postify._transport import RequestSpec, build_headers, redacted_headers

from .conftest import API_KEY, BASE_URL, channel


@respx.mock
def test_bearer_is_the_default_auth_scheme(client: Postify) -> None:
    route = respx.get(f"{BASE_URL}/v1/channels").mock(
        return_value=httpx.Response(200, json={"data": [channel()]})
    )
    client.channels.list()
    sent = route.calls[0].request
    assert sent.headers["authorization"] == f"Bearer {API_KEY}"
    assert "x-api-key" not in sent.headers


@respx.mock
def test_auth_style_header_switches_to_x_api_key() -> None:
    route = respx.get(f"{BASE_URL}/v1/channels").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    with Postify(api_key=API_KEY, base_url=BASE_URL, auth_style="header") as client:
        client.channels.list()
    sent = route.calls[0].request
    assert sent.headers["x-api-key"] == API_KEY
    assert "authorization" not in sent.headers


@respx.mock
async def test_async_client_sends_the_same_auth_header() -> None:
    route = respx.get(f"{BASE_URL}/v1/channels").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    async with AsyncPostify(api_key=API_KEY, base_url=BASE_URL) as client:
        await client.channels.list()
    assert route.calls[0].request.headers["authorization"] == f"Bearer {API_KEY}"


@respx.mock
def test_user_agent_identifies_the_sdk_httpx_and_python(client: Postify) -> None:
    route = respx.get(f"{BASE_URL}/v1/usage").mock(
        return_value=httpx.Response(200, json={"plan": "team", "meters": []})
    )
    client.usage.get()
    agent = route.calls[0].request.headers["user-agent"]
    assert agent.startswith("postify-python/0.1.0 ")
    assert "httpx/" in agent
    assert "python/" in agent


@respx.mock
def test_default_headers_are_sent_but_cannot_clobber_authentication() -> None:
    route = respx.get(f"{BASE_URL}/v1/channels").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    with Postify(
        api_key=API_KEY,
        base_url=BASE_URL,
        default_headers={"X-App": "my-service", "Authorization": "Bearer attacker"},
    ) as client:
        client.channels.list()
    sent = route.calls[0].request
    assert sent.headers["x-app"] == "my-service"
    assert sent.headers["authorization"] == f"Bearer {API_KEY}"


def test_an_invalid_auth_style_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        Postify(api_key=API_KEY, auth_style="basic")


def test_a_missing_api_key_raises_a_helpful_postify_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("POSTIFY_API_KEY", raising=False)
    with pytest.raises(PostifyError) as excinfo:
        Postify()
    assert "POSTIFY_API_KEY" in str(excinfo.value)


def test_the_api_key_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTIFY_API_KEY", API_KEY)
    with Postify() as client:
        assert client.api_key == API_KEY


def test_redact_api_key_keeps_only_the_prefix_and_last_four_characters() -> None:
    assert redact_api_key("postify_live_abcdefgh1234") == "postify_live_…1234"
    assert redact_api_key("postify_test_abcdefgh9999") == "postify_test_…9999"
    assert redact_api_key("short") == "…"
    assert redact_api_key("") == "<unset>"


def test_the_key_never_appears_in_repr_or_str() -> None:
    with Postify(api_key=API_KEY, base_url=BASE_URL) as client:
        for rendered in (repr(client), str(client)):
            assert API_KEY not in rendered
            assert "postify_live_…1234" in rendered


def test_redacted_headers_masks_both_credential_schemes() -> None:
    bearer = build_headers(api_key=API_KEY, auth_style="bearer", version="0.1.0")
    header = build_headers(api_key=API_KEY, auth_style="header", version="0.1.0")
    assert API_KEY not in str(redacted_headers(bearer))
    assert API_KEY not in str(redacted_headers(header))
    assert redacted_headers(header)["x-api-key"] == "postify_live_…1234"


def test_content_type_is_only_set_when_there_is_a_json_body() -> None:
    without = build_headers(api_key=API_KEY, auth_style="bearer", version="0.1.0")
    with_body = build_headers(
        api_key=API_KEY, auth_style="bearer", version="0.1.0", has_json_body=True
    )
    assert "Content-Type" not in without
    assert with_body["Content-Type"] == "application/json"


def test_a_caller_supplied_request_id_is_forwarded() -> None:
    headers = build_headers(
        api_key=API_KEY, auth_style="bearer", version="0.1.0", request_id="req_mine"
    )
    assert headers["x-request-id"] == "req_mine"


def test_request_specs_know_which_requests_may_be_retried() -> None:
    assert RequestSpec(method="GET", path="/v1/posts").is_retryable
    assert not RequestSpec(method="DELETE", path="/v1/posts/1").is_retryable
    assert RequestSpec(method="POST", path="/v1/posts", idempotency_key="k").is_retryable
