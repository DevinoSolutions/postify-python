"""Retry policy: what is retried, what is never retried, and how long we wait."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest
import respx

from postify import (
    APIConnectionError,
    APITimeoutError,
    AsyncPostify,
    ConflictError,
    InternalServerError,
    Postify,
    RateLimitError,
)
from postify._transport import next_delay, parse_retry_after, should_retry

from .conftest import API_KEY, BASE_URL, post, problem

# --------------------------------------------------------------------------- #
# The pure policy functions
# --------------------------------------------------------------------------- #


def test_retry_after_is_parsed_in_delta_seconds_form() -> None:
    assert parse_retry_after("2") == 2.0
    assert parse_retry_after("0") == 0.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("not-a-date") is None


def test_retry_after_is_parsed_in_http_date_form() -> None:
    when = datetime.now(timezone.utc) + timedelta(seconds=30)
    parsed = parse_retry_after(format_datetime(when, usegmt=True))
    assert parsed is not None
    assert 25 <= parsed <= 31


def test_an_http_date_in_the_past_yields_zero_not_a_negative_delay() -> None:
    when = datetime.now(timezone.utc) - timedelta(seconds=120)
    assert parse_retry_after(format_datetime(when, usegmt=True)) == 0.0


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (408, None, True),
        (409, "idempotency_in_progress", True),
        (409, "resource_conflict", False),
        (429, "rate_limited", True),
        (429, "quota_exhausted", False),
        (500, "internal_error", True),
        (502, None, True),
        (503, None, True),
        (504, None, True),
        (400, "invalid_request", False),
        (401, "invalid_api_key", False),
        (403, "insufficient_scope", False),
        (404, "resource_not_found", False),
        (422, "idempotency_key_reused", False),
    ],
)
def test_the_status_retry_table(status: int, code: str, expected: bool) -> None:
    assert (
        should_retry(attempt=0, max_retries=2, retryable_request=True, status=status, code=code)
        is expected
    )


def test_an_unkeyed_mutation_is_never_retried_whatever_happened() -> None:
    for kwargs in (
        {"is_connection_error": True},
        {"status": 429, "code": "rate_limited"},
        {"status": 503},
        {"status": 408},
    ):
        assert should_retry(attempt=0, max_retries=5, retryable_request=False, **kwargs) is False


def test_max_retries_zero_disables_retrying_entirely() -> None:
    assert (
        should_retry(attempt=0, max_retries=0, retryable_request=True, is_connection_error=True)
        is False
    )


def test_attempts_stop_once_the_budget_is_spent() -> None:
    assert should_retry(attempt=1, max_retries=2, retryable_request=True, status=500) is True
    assert should_retry(attempt=2, max_retries=2, retryable_request=True, status=500) is False


def test_an_absurdly_long_retry_after_is_surfaced_rather_than_slept_through() -> None:
    assert (
        should_retry(
            attempt=0,
            max_retries=2,
            retryable_request=True,
            status=429,
            code="rate_limited",
            retry_after_seconds=3600.0,
        )
        is False
    )


def test_backoff_is_full_jitter_and_bounded_by_the_cap() -> None:
    for attempt in range(6):
        for _ in range(50):
            delay = next_delay(attempt=attempt)
            assert 0.0 <= delay <= min(8.0, 0.5 * (2**attempt))


def test_retry_after_wins_over_backoff_and_over_the_rate_limit_window() -> None:
    assert next_delay(attempt=3, retry_after_seconds=2.0, rate_limit_reset_seconds=30.0) == 2.0


def test_the_rate_limit_window_is_used_when_there_is_no_retry_after() -> None:
    assert next_delay(attempt=0, rate_limit_reset_seconds=3.0) == 3.0
    assert next_delay(attempt=0, rate_limit_reset_seconds=999.0) == 8.0


# --------------------------------------------------------------------------- #
# The policy as observed through the client
# --------------------------------------------------------------------------- #


@respx.mock
def test_a_rate_limited_get_is_retried_and_honors_retry_after(
    client: Postify, slept: list[float]
) -> None:
    respx.get(f"{BASE_URL}/v1/posts/pst_1").mock(
        side_effect=[
            httpx.Response(429, json=problem(429, "rate_limited"), headers={"Retry-After": "2"}),
            httpx.Response(200, json=post()),
        ]
    )
    assert client.posts.get("pst_1").id == "pst_1"
    assert slept == [2.0]


@respx.mock
def test_quota_exhausted_is_never_retried(client: Postify, slept: list[float]) -> None:
    route = respx.get(f"{BASE_URL}/v1/posts/pst_1").mock(
        return_value=httpx.Response(429, json=problem(429, "quota_exhausted"))
    )
    with pytest.raises(RateLimitError) as excinfo:
        client.posts.get("pst_1")
    assert excinfo.value.code == "quota_exhausted"
    assert route.call_count == 1
    assert slept == []


@respx.mock
def test_a_server_error_is_retried_up_to_max_retries_then_raises(client: Postify) -> None:
    route = respx.get(f"{BASE_URL}/v1/analytics").mock(
        return_value=httpx.Response(503, json=problem(503, "internal_error"))
    )
    with pytest.raises(InternalServerError):
        client.analytics.get()
    assert route.call_count == 3  # 1 attempt + 2 retries


@respx.mock
def test_max_retries_zero_makes_exactly_one_attempt() -> None:
    route = respx.get(f"{BASE_URL}/v1/analytics").mock(
        return_value=httpx.Response(500, json=problem(500, "internal_error"))
    )
    with Postify(api_key=API_KEY, base_url=BASE_URL, max_retries=0) as client:
        with pytest.raises(InternalServerError):
            client.analytics.get()
    assert route.call_count == 1


@respx.mock
def test_a_connection_error_on_a_get_is_retried(client: Postify) -> None:
    route = respx.get(f"{BASE_URL}/v1/analytics").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json=_analytics())]
    )
    client.analytics.get()
    assert route.call_count == 2


@respx.mock
def test_a_timeout_surfaces_as_api_timeout_error_after_the_budget(client: Postify) -> None:
    respx.get(f"{BASE_URL}/v1/analytics").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(APITimeoutError):
        client.analytics.get()


@respx.mock
def test_an_unkeyed_mutation_is_not_retried_on_a_connection_failure(
    client: Postify,
) -> None:
    route = respx.delete(f"{BASE_URL}/v1/posts/pst_1").mock(side_effect=httpx.ConnectError("reset"))
    with pytest.raises(APIConnectionError):
        client.posts.delete("pst_1")
    assert route.call_count == 1


@respx.mock
def test_an_unkeyed_mutation_is_not_retried_on_a_server_error(client: Postify) -> None:
    route = respx.post(f"{BASE_URL}/v1/posts/pst_1/publish").mock(
        return_value=httpx.Response(503, json=problem(503, "internal_error"))
    )
    with pytest.raises(InternalServerError):
        client.posts.publish("pst_1")
    assert route.call_count == 1


@respx.mock
def test_a_keyed_create_is_retried_on_a_connection_failure(client: Postify) -> None:
    route = respx.post(f"{BASE_URL}/v1/posts").mock(
        side_effect=[httpx.ConnectError("reset"), httpx.Response(201, json=post())]
    )
    created = client.posts.create(variants=[{"channel_id": "chn_1", "body": "hi"}], draft=True)
    assert created.id == "pst_1"
    assert route.call_count == 2
    keys = {call.request.headers["idempotency-key"] for call in route.calls}
    assert len(keys) == 1  # the SAME key on the retry, or it would not be idempotent


@respx.mock
def test_idempotency_in_progress_is_retried_with_the_servers_retry_after(
    client: Postify, slept: list[float]
) -> None:
    respx.post(f"{BASE_URL}/v1/posts").mock(
        side_effect=[
            httpx.Response(
                409,
                json=problem(409, "idempotency_in_progress"),
                headers={"Retry-After": "2"},
            ),
            httpx.Response(201, json=post()),
        ]
    )
    client.posts.create(variants=[{"channel_id": "chn_1", "body": "hi"}], draft=True)
    assert slept == [2.0]


@respx.mock
def test_a_plain_resource_conflict_is_not_retried(client: Postify) -> None:
    route = respx.post(f"{BASE_URL}/v1/posts").mock(
        return_value=httpx.Response(409, json=problem(409, "resource_conflict"))
    )
    with pytest.raises(ConflictError):
        client.posts.create(variants=[{"channel_id": "chn_1", "body": "hi"}], draft=True)
    assert route.call_count == 1


@respx.mock
def test_a_per_call_max_retries_of_zero_overrides_the_client_default() -> None:
    route = respx.get(f"{BASE_URL}/v1/analytics").mock(
        return_value=httpx.Response(500, json=problem(500, "internal_error"))
    )
    with Postify(api_key=API_KEY, base_url=BASE_URL, max_retries=4) as client:
        client.max_retries = 1
        with pytest.raises(InternalServerError):
            client.analytics.get()
    assert route.call_count == 2


@respx.mock
async def test_the_async_client_applies_the_identical_policy() -> None:
    route = respx.get(f"{BASE_URL}/v1/analytics").mock(
        side_effect=[
            httpx.Response(500, json=problem(500, "internal_error")),
            httpx.Response(200, json=_analytics()),
        ]
    )
    async with AsyncPostify(api_key=API_KEY, base_url=BASE_URL) as client:
        await client.analytics.get()
    assert route.call_count == 2


@respx.mock
async def test_the_async_client_also_refuses_to_retry_unkeyed_mutations() -> None:
    route = respx.delete(f"{BASE_URL}/v1/posts/pst_1").mock(side_effect=httpx.ConnectError("reset"))
    async with AsyncPostify(api_key=API_KEY, base_url=BASE_URL) as client:
        with pytest.raises(APIConnectionError):
            await client.posts.delete("pst_1")
    assert route.call_count == 1


def _analytics() -> dict:
    from .conftest import analytics

    return analytics()
