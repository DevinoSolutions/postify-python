"""Rate-limit header parsing — both generations, and never inventing a value."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx

from postify import Postify, RateLimitError, parse_rate_limit

from .conftest import BASE_URL, problem, usage

NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)


def test_draft11_structured_fields_are_parsed() -> None:
    state = parse_rate_limit(
        {
            "RateLimit-Policy": '"per-key-minute";q=120;w=60',
            "RateLimit": '"per-key-minute";r=73;t=38',
        },
        now=NOW,
    )
    assert state is not None
    assert state.policy == "per-key-minute"
    assert state.limit == 120
    assert state.window_sec == 60
    assert state.remaining == 73
    assert state.seconds_until_reset(NOW) == 38.0


def test_the_legacy_x_trio_is_used_as_a_fallback() -> None:
    state = parse_rate_limit(
        {
            "X-RateLimit-Limit": "120",
            "X-RateLimit-Remaining": "73",
            "X-RateLimit-Reset": "1786000000",
        },
        now=NOW,
    )
    assert state is not None
    assert state.limit == 120
    assert state.remaining == 73
    assert state.reset_at == datetime.fromtimestamp(1786000000, tz=timezone.utc)
    assert state.policy is None


def test_draft11_values_win_over_the_legacy_trio() -> None:
    state = parse_rate_limit(
        {
            "RateLimit-Policy": '"per-key-minute";q=120;w=60',
            "RateLimit": '"per-key-minute";r=5;t=10',
            "X-RateLimit-Limit": "999",
            "X-RateLimit-Remaining": "888",
        },
        now=NOW,
    )
    assert state is not None
    assert state.limit == 120
    assert state.remaining == 5


def test_an_unobservable_window_leaves_remaining_none_rather_than_full() -> None:
    """Policy + limit but no RateLimit member means "not observable", not "full"."""
    state = parse_rate_limit(
        {"RateLimit-Policy": '"per-key-minute";q=120;w=60', "X-RateLimit-Limit": "120"},
        now=NOW,
    )
    assert state is not None
    assert state.limit == 120
    assert state.remaining is None
    assert state.reset_at is None
    assert state.seconds_until_reset(NOW) is None


def test_a_response_without_any_rate_limit_headers_yields_none() -> None:
    assert parse_rate_limit({"Content-Type": "application/json"}) is None


def test_a_rate_limit_member_without_a_reset_still_reports_remaining() -> None:
    state = parse_rate_limit({"RateLimit": '"per-key-minute";r=7'}, now=NOW)
    assert state is not None
    assert state.remaining == 7
    assert state.reset_at is None


def test_header_lookup_is_case_insensitive() -> None:
    state = parse_rate_limit({"ratelimit-policy": '"burst";q=10;w=1'}, now=NOW)
    assert state is not None
    assert state.policy == "burst"


def test_garbage_parameter_values_are_ignored_not_fatal() -> None:
    state = parse_rate_limit({"RateLimit-Policy": '"burst";q=lots;w=60'}, now=NOW)
    assert state is not None
    assert state.limit is None
    assert state.window_sec == 60


@respx.mock
def test_the_client_exposes_the_window_from_the_last_response(client: Postify) -> None:
    respx.get(f"{BASE_URL}/v1/usage").mock(
        return_value=httpx.Response(
            200,
            json=usage(),
            headers={
                "RateLimit-Policy": '"per-key-minute";q=120;w=60',
                "RateLimit": '"per-key-minute";r=73;t=38',
                "Request-Id": "req_usage",
            },
        )
    )
    result = client.usage.get()
    assert client.last_rate_limit is not None
    assert client.last_rate_limit.remaining == 73
    assert client.last_request_id == "req_usage"
    # The same snapshot rides along on the model.
    assert result.rate_limit is not None
    assert result.rate_limit.limit == 120
    assert result.meter("api_requests").used == 412
    assert result.meter("nonexistent") is None


@respx.mock
def test_errors_carry_the_window_and_the_parsed_retry_after(client: Postify) -> None:
    client.max_retries = 0
    respx.get(f"{BASE_URL}/v1/usage").mock(
        return_value=httpx.Response(
            429,
            json=problem(429, "rate_limited"),
            headers={
                "RateLimit-Policy": '"per-key-minute";q=120;w=60',
                "RateLimit": '"per-key-minute";r=0;t=15',
                "Retry-After": "15",
            },
        )
    )
    with pytest.raises(RateLimitError) as excinfo:
        client.usage.get()
    assert excinfo.value.retry_after_seconds == 15.0
    assert excinfo.value.rate_limit is not None
    assert excinfo.value.rate_limit.remaining == 0
