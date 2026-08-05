"""Models validate against instances synthesized from the vendored OpenAPI schemas.

Rather than hand-copying example payloads, this builds a conforming instance for
each response schema straight out of ``spec/v1.json`` (resolving ``$ref``s and
honoring declared examples/enums) and feeds it to the matching pydantic model. A
field the server declares as required but the SDK never modelled fails here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from postify import models

SPEC_PATH = Path(__file__).resolve().parents[2] / "spec" / "v1.json"
SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
SCHEMAS = SPEC["components"]["schemas"]

# Every response schema in the spec, mapped to the model that must accept it.
SCHEMA_TO_MODEL = {
    "Channel": models.Channel,
    "ChannelList": models.ChannelList,
    "Post": models.Post,
    "PostList": models.PostList,
    "PostVariant": models.PostVariant,
    "Delivery": models.Delivery,
    "PostMediaItemOutput": models.PostMediaItem,
    "DeletePostResponse": models.DeletePostResponse,
    "PublishPostResponse": models.PublishPostResponse,
    "MediaAsset": models.MediaAsset,
    "MediaList": models.MediaList,
    "CreateUploadResponse": models.CreateUploadResponse,
    "Analytics": models.Analytics,
    "AnalyticsTimelinePoint": models.AnalyticsTimelinePoint,
    "Usage": models.Usage,
    "UsageMeter": models.UsageMeter,
    "WebhookEndpoint": models.WebhookEndpoint,
    "WebhookEndpointList": models.WebhookEndpointList,
    "WebhookEndpointCreated": models.WebhookEndpointCreated,
    "DeleteWebhookEndpointResponse": models.DeleteWebhookEndpointResponse,
    "TestWebhookEndpointResult": models.TestWebhookEndpointResult,
}


def resolve(schema: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        schema = SCHEMAS[schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def synthesize(schema: dict[str, Any], depth: int = 0) -> Any:
    """Build one conforming instance of a JSON Schema node."""
    schema = resolve(schema)
    if "example" in schema:
        return schema["example"]
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    for combinator in ("allOf", "anyOf", "oneOf"):
        if combinator in schema:
            options = [
                option for option in schema[combinator] if resolve(option).get("type") != "null"
            ]
            if combinator == "allOf":
                merged: dict[str, Any] = {}
                for option in options:
                    built = synthesize(option, depth + 1)
                    if isinstance(built, dict):
                        merged.update(built)
                return merged
            return synthesize(options[0], depth + 1)

    declared = schema.get("type")
    kind = declared[0] if isinstance(declared, list) else declared
    if kind == "object" or "properties" in schema:
        return {
            name: synthesize(child, depth + 1)
            for name, child in schema.get("properties", {}).items()
        }
    if kind == "array":
        if depth > 4:
            return []
        return [synthesize(schema.get("items", {}), depth + 1)]
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    return "example"


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_TO_MODEL))
def test_each_response_schema_validates_against_its_model(schema_name: str) -> None:
    instance = synthesize(SCHEMAS[schema_name])
    model = SCHEMA_TO_MODEL[schema_name].model_validate(instance)
    assert model is not None


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_TO_MODEL))
def test_every_required_spec_property_is_a_declared_model_field(schema_name: str) -> None:
    schema = resolve(SCHEMAS[schema_name])
    required = set(schema.get("required", []))
    if "allOf" in schema:
        for option in schema["allOf"]:
            required |= set(resolve(option).get("required", []))
    declared = set(SCHEMA_TO_MODEL[schema_name].model_fields)
    assert required <= declared, f"{schema_name} is missing {sorted(required - declared)}"


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_TO_MODEL))
def test_models_round_trip_through_model_dump(schema_name: str) -> None:
    instance = synthesize(SCHEMAS[schema_name])
    model_cls = SCHEMA_TO_MODEL[schema_name]
    once = model_cls.model_validate(instance)
    twice = model_cls.model_validate(once.model_dump())
    assert once.model_dump() == twice.model_dump()


def test_unknown_server_fields_are_preserved_not_rejected() -> None:
    """Postify's contracts are additive — a new field must never break a client."""
    channel = models.Channel.model_validate(
        {
            "id": "chn_1",
            "platform": "bluesky",
            "handle": "@acme",
            "avatar_url": None,
            "followers": None,
            "status": "live",
            "last_sync_at": None,
            "last_error": None,
            "created_at": "2026-08-05T12:00:00.000Z",
            "brand_new_field": {"shipped": "after this SDK release"},
        }
    )
    assert channel.model_dump()["brand_new_field"] == {"shipped": "after this SDK release"}


def test_an_unknown_platform_or_status_does_not_raise() -> None:
    channel = models.Channel.model_validate(
        {
            "id": "chn_1",
            "platform": "mastodon",  # not in this SDK's PLATFORMS tuple
            "handle": "@acme",
            "avatar_url": None,
            "followers": None,
            "status": "quarantined",
            "last_sync_at": None,
            "last_error": None,
            "created_at": "2026-08-05T12:00:00.000Z",
        }
    )
    assert channel.platform == "mastodon"
    assert channel.status == "quarantined"


def test_the_exported_vocabularies_match_the_spec_enums() -> None:
    assert set(models.CHANNEL_STATUSES) == set(SCHEMAS["Channel"]["properties"]["status"]["enum"])
    assert set(models.POST_STATUSES) == set(SCHEMAS["Post"]["properties"]["status"]["enum"])
    assert set(models.POST_TYPES) == set(SCHEMAS["Post"]["properties"]["type"]["enum"])
    assert set(models.MEDIA_KINDS) == set(SCHEMAS["MediaAsset"]["properties"]["kind"]["enum"])
    assert set(models.MEDIA_STATUSES) == set(SCHEMAS["MediaAsset"]["properties"]["status"]["enum"])
    assert set(models.USAGE_METERS) == set(SCHEMAS["UsageMeter"]["properties"]["key"]["enum"])
    assert set(models.PLATFORMS) == set(SCHEMAS["Channel"]["properties"]["platform"]["enum"])
    assert set(models.POST_DELIVERY_STAGES) == set(
        SCHEMAS["Delivery"]["properties"]["stage"]["enum"]
    )


def test_the_webhook_event_catalog_matches_the_spec() -> None:
    spec_types = set(SCHEMAS["WebhookEndpoint"]["properties"]["event_types"]["items"]["enum"])
    assert set(models.WEBHOOK_EVENT_TYPES) == spec_types


def test_response_metadata_defaults_are_inert_until_stamped() -> None:
    post = models.Post.model_validate(
        {
            "id": "pst_1",
            "status": "draft",
            "type": "single",
            "title": None,
            "body": None,
            "scheduled_at": None,
            "published_at": None,
            "created_at": "2026-08-05T12:00:00.000Z",
            "variants": [],
            "deliveries": [],
        }
    )
    assert post.request_id is None
    assert post.idempotency_replayed is False
    assert post.rate_limit is None
