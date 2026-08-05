"""RFC 9457 problem documents map to the right exception, code and metadata."""

from __future__ import annotations

import httpx
import pytest
import respx

from postify import (
    PROBLEM_CODES,
    APIError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    Postify,
    RateLimitError,
    UnprocessableEntityError,
    problem_type_uri,
)

from .conftest import BASE_URL, problem

STATUS_TO_CLASS = [
    (400, "invalid_request", BadRequestError),
    (400, "validation_failed", BadRequestError),
    (401, "authentication_required", AuthenticationError),
    (401, "invalid_api_key", AuthenticationError),
    (403, "insufficient_scope", PermissionDeniedError),
    (403, "feature_not_enabled", PermissionDeniedError),
    (403, "dangerous_ops_disabled", PermissionDeniedError),
    (404, "resource_not_found", NotFoundError),
    (409, "resource_conflict", ConflictError),
    (409, "idempotency_in_progress", ConflictError),
    (422, "idempotency_key_reused", UnprocessableEntityError),
    (429, "rate_limited", RateLimitError),
    (429, "quota_exhausted", RateLimitError),
    (500, "internal_error", InternalServerError),
]


@pytest.mark.parametrize(("status", "code", "expected"), STATUS_TO_CLASS)
@respx.mock
def test_each_problem_code_raises_its_documented_exception_class(
    client: Postify, status: int, code: str, expected: type
) -> None:
    respx.get(f"{BASE_URL}/v1/posts/pst_1").mock(
        return_value=httpx.Response(
            status,
            json=problem(status, code),
            headers={"Content-Type": "application/problem+json"},
        )
    )
    client.max_retries = 0
    with pytest.raises(expected) as excinfo:
        client.posts.get("pst_1")
    err = excinfo.value
    assert err.status == status
    assert err.code == code
    assert err.problem_type == problem_type_uri(code)


def test_the_registry_covers_every_code_the_server_can_emit() -> None:
    assert len(PROBLEM_CODES) == 14
    for status, code, _ in STATUS_TO_CLASS:
        assert PROBLEM_CODES[code]["status"] == status


@respx.mock
def test_an_unknown_future_problem_code_degrades_instead_of_crashing(
    client: Postify,
) -> None:
    client.max_retries = 0
    respx.get(f"{BASE_URL}/v1/posts/pst_1").mock(
        return_value=httpx.Response(
            418,
            json={
                "type": "https://usepostify.com/docs/api/problems/tea-pot",
                "title": "I am a teapot",
                "status": 418,
                "code": "brewing_in_progress",
                "request_id": "req_teapot",
            },
        )
    )
    with pytest.raises(APIError) as excinfo:
        client.posts.get("pst_1")
    assert type(excinfo.value) is APIError
    assert excinfo.value.code == "brewing_in_progress"
    assert excinfo.value.request_id == "req_teapot"


@respx.mock
def test_field_errors_are_populated_on_validation_failed(client: Postify) -> None:
    client.max_retries = 0
    respx.post(f"{BASE_URL}/v1/posts").mock(
        return_value=httpx.Response(
            400,
            json=problem(
                400,
                "validation_failed",
                detail="Exactly one publishing mode is required.",
                field_errors=[
                    {
                        "pointer": "/scheduled_at",
                        "code": "custom",
                        "message": "Exactly one of `draft: true`, `scheduled_at`, or "
                        "`publish_now: true` is required.",
                    }
                ],
            ),
        )
    )
    with pytest.raises(BadRequestError) as excinfo:
        client.posts.create(variants=[{"channel_id": "chn_1", "body": "hi"}])
    assert [f.pointer for f in excinfo.value.field_errors] == ["/scheduled_at"]
    assert "Exactly one" in excinfo.value.field_errors[0].message


@respx.mock
def test_request_id_is_read_from_the_body(client: Postify) -> None:
    client.max_retries = 0
    respx.get(f"{BASE_URL}/v1/analytics").mock(
        return_value=httpx.Response(404, json=problem(404, "resource_not_found"))
    )
    with pytest.raises(NotFoundError) as excinfo:
        client.analytics.get()
    assert excinfo.value.request_id == "req_9f2c1e4ab8d64f0e"


@respx.mock
def test_request_id_falls_back_to_the_response_header(client: Postify) -> None:
    client.max_retries = 0
    respx.get(f"{BASE_URL}/v1/analytics").mock(
        return_value=httpx.Response(
            404,
            json={"status": 404, "code": "resource_not_found", "title": "Resource not found"},
            headers={"Request-Id": "req_from_header"},
        )
    )
    with pytest.raises(NotFoundError) as excinfo:
        client.analytics.get()
    assert excinfo.value.request_id == "req_from_header"


@respx.mock
def test_a_non_json_error_body_still_produces_a_typed_error(client: Postify) -> None:
    client.max_retries = 0
    respx.get(f"{BASE_URL}/v1/analytics").mock(
        return_value=httpx.Response(502, text="<html>bad gateway</html>")
    )
    with pytest.raises(InternalServerError) as excinfo:
        client.analytics.get()
    assert excinfo.value.status == 502
    assert excinfo.value.title == "HTTP 502"


@respx.mock
def test_the_error_string_carries_status_code_title_detail_and_request_id(
    client: Postify,
) -> None:
    client.max_retries = 0
    respx.get(f"{BASE_URL}/v1/posts/pst_1").mock(
        return_value=httpx.Response(
            403, json=problem(403, "insufficient_scope", detail="Needs posts:read.")
        )
    )
    with pytest.raises(PermissionDeniedError) as excinfo:
        client.posts.get("pst_1")
    rendered = str(excinfo.value)
    assert rendered.startswith("403 insufficient_scope: ")
    assert "Needs posts:read." in rendered
    assert "request_id: req_9f2c1e4ab8d64f0e" in rendered


@respx.mock
def test_a_401_carries_the_www_authenticate_challenge(client: Postify) -> None:
    client.max_retries = 0
    respx.get(f"{BASE_URL}/v1/channels").mock(
        return_value=httpx.Response(
            401,
            json=problem(401, "invalid_api_key"),
            headers={"WWW-Authenticate": "Bearer"},
        )
    )
    with pytest.raises(AuthenticationError) as excinfo:
        client.channels.list()
    assert excinfo.value.headers["www-authenticate"] == "Bearer"


def test_problem_type_uris_hyphenate_the_code() -> None:
    assert problem_type_uri("quota_exhausted").endswith("/quota-exhausted")


def test_empty_path_parameters_are_rejected_before_a_request_is_made(
    client: Postify,
) -> None:
    with pytest.raises(ValueError):
        client.posts.get("")
