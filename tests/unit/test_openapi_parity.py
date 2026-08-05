"""The release gate: the SDK covers exactly the operations ``/v1`` exposes.

``spec/v1.json`` is the vendored OpenAPI artifact the server generates from the
same zod schemas its handlers validate with. If the server grows an operation and
this SDK does not, CI fails here — which is the coverage guarantee a code
generator would give us, without generated code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from postify import OPERATIONS, AsyncPostify, Postify

SPEC_PATH = Path(__file__).resolve().parents[2] / "spec" / "v1.json"
HTTP_METHODS = {"get", "put", "post", "patch", "delete", "head", "options", "trace"}


@pytest.fixture(scope="module")
def spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def spec_operations(spec: dict) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, operations in spec["paths"].items()
        for method in operations
        if method.lower() in HTTP_METHODS
    }


def test_vendored_spec_is_present_and_parseable(spec: dict) -> None:
    assert spec["openapi"].startswith("3.1")
    assert spec["info"]["title"] == "Postify API"
    assert spec["servers"][0]["url"] == "https://app.usepostify.com"


def test_the_spec_declares_exactly_seventeen_authenticated_operations(spec: dict) -> None:
    assert len(spec_operations(spec)) == 17


def test_every_openapi_operation_has_an_sdk_method(spec: dict) -> None:
    """Both directions: no server operation unimplemented, no SDK method invented."""
    from_spec = spec_operations(spec)
    from_sdk = {(op.method, op.path) for op in OPERATIONS}

    missing_in_sdk = from_spec - from_sdk
    invented_by_sdk = from_sdk - from_spec
    assert not missing_in_sdk, f"SDK is missing operations: {sorted(missing_in_sdk)}"
    assert not invented_by_sdk, f"SDK claims non-existent operations: {sorted(invented_by_sdk)}"


def test_operation_ids_match_the_spec(spec: dict) -> None:
    spec_ids = {
        (method.upper(), path): operation.get("operationId")
        for path, operations in spec["paths"].items()
        for method, operation in operations.items()
        if method.lower() in HTTP_METHODS
    }
    for op in OPERATIONS:
        assert spec_ids[(op.method, op.path)] == op.operation_id


def test_success_status_codes_match_the_spec(spec: dict) -> None:
    for op in OPERATIONS:
        responses = spec["paths"][op.path][op.method.lower()]["responses"]
        assert str(op.success_status) in responses, op.operation_id


def test_only_create_post_declares_an_idempotency_key_header(spec: dict) -> None:
    for op in OPERATIONS:
        params = spec["paths"][op.path][op.method.lower()].get("parameters", [])
        declares = any(
            param.get("in") == "header" and param.get("name") == "Idempotency-Key"
            for param in params
        )
        assert declares == op.idempotent, op.operation_id


def test_every_registered_operation_resolves_to_a_real_sync_method() -> None:
    client = Postify(api_key="postify_live_examplekey1234")
    try:
        for op in OPERATIONS:
            resource = getattr(client, op.resource)
            method = getattr(resource, op.method_name, None)
            assert callable(method), f"{op.resource}.{op.method_name} is missing"
    finally:
        client.close()


def test_every_registered_operation_resolves_to_a_real_async_method() -> None:
    client = AsyncPostify(api_key="postify_live_examplekey1234")
    for op in OPERATIONS:
        resource = getattr(client, op.resource)
        method = getattr(resource, op.method_name, None)
        assert callable(method), f"async {op.resource}.{op.method_name} is missing"


def test_paginated_operations_are_exactly_posts_list_and_media_list() -> None:
    paginated = {op.operation_id for op in OPERATIONS if op.paginated}
    assert paginated == {"listPosts", "listMedia"}


def test_both_security_schemes_from_the_spec_are_supported(spec: dict) -> None:
    schemes = spec["components"]["securitySchemes"]
    assert schemes["bearerApiKey"]["scheme"] == "bearer"
    assert schemes["headerApiKey"]["name"] == "x-api-key"
