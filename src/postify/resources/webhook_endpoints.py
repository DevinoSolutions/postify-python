"""``/v1/webhook-endpoints`` — manage outbound webhook subscribers.

Not paginated: the endpoint count is bounded by the plan's ``integrations``
quota, so ``list()`` returns a plain list.

The signing secret is shown **once**, in the create response. Store it then —
over the API there is no way to read it back (a workspace owner/admin can
re-reveal or roll it in Settings → Webhooks).
"""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from typing import Any, Union

from postify._transport import RequestSpec
from postify._types import NOT_GIVEN, NotGiven
from postify.models import (
    DeleteWebhookEndpointResponse,
    TestWebhookEndpointResult,
    WebhookEndpoint,
    WebhookEndpointCreated,
    WebhookEndpointList,
    WebhookEventType,
)

from ._base import AsyncResource, SyncResource, parse_model, prune, require_id

__all__ = ["AsyncWebhookEndpoints", "WebhookEndpoints"]

_COLLECTION = "/v1/webhook-endpoints"


def _item(endpoint_id: str) -> str:
    return f"{_COLLECTION}/{require_id(endpoint_id, 'endpoint_id')}"


def _update_body(
    url: Union[str, NotGiven],
    event_types: Union[Sequence[WebhookEventType], NotGiven],
    enabled: Union[bool, NotGiven],
) -> dict[str, Any]:
    body = prune({"url": url, "event_types": event_types, "enabled": enabled})
    if not body:
        raise ValueError("update() needs at least one of url, event_types or enabled")
    if "event_types" in body:
        body["event_types"] = list(body["event_types"])
    return body


class WebhookEndpoints(SyncResource):
    """Webhook endpoints. Scopes: ``webhooks:read`` / ``webhooks:write``."""

    def list(self) -> builtins.list[WebhookEndpoint]:
        """List every webhook endpoint on the workspace."""
        response = self._client.request(RequestSpec(method="GET", path=_COLLECTION))
        return parse_model(WebhookEndpointList, response).data

    def create(
        self, *, url: str, event_types: Sequence[WebhookEventType]
    ) -> WebhookEndpointCreated:
        """Create an endpoint and receive its **show-once** signing secret.

        The URL must be HTTPS on port 443 and survive the SSRF gauntlet — private,
        loopback, link-local and cloud-metadata addresses are rejected here and
        again at every delivery.

        Example::

            endpoint = client.webhook_endpoints.create(
                url="https://api.example.com/postify/webhooks",
                event_types=["post.published", "post.failed"],
            )
            save_secret(endpoint.signing_secret)  # shown only once
        """
        response = self._client.request(
            RequestSpec(
                method="POST",
                path=_COLLECTION,
                json_body={"url": url, "event_types": list(event_types)},
            )
        )
        return parse_model(WebhookEndpointCreated, response)

    def update(
        self,
        endpoint_id: str,
        *,
        url: Union[str, NotGiven] = NOT_GIVEN,
        event_types: Union[Sequence[WebhookEventType], NotGiven] = NOT_GIVEN,
        enabled: Union[bool, NotGiven] = NOT_GIVEN,
    ) -> WebhookEndpoint:
        """Partially update an endpoint. Unmentioned fields are left untouched.

        Setting ``enabled=True`` on an auto-disabled endpoint clears its failure
        state and resumes deliveries.
        """
        response = self._client.request(
            RequestSpec(
                method="PATCH",
                path=_item(endpoint_id),
                json_body=_update_body(url, event_types, enabled),
            )
        )
        return parse_model(WebhookEndpoint, response)

    def delete(self, endpoint_id: str) -> DeleteWebhookEndpointResponse:
        """Delete an endpoint. Deliveries stop immediately."""
        response = self._client.request(RequestSpec(method="DELETE", path=_item(endpoint_id)))
        return parse_model(DeleteWebhookEndpointResponse, response)

    def test(self, endpoint_id: str) -> TestWebhookEndpointResult:
        """Send a synthetic ``webhook.test`` delivery, signed like a real event."""
        response = self._client.request(
            RequestSpec(method="POST", path=f"{_item(endpoint_id)}/test")
        )
        return parse_model(TestWebhookEndpointResult, response)


class AsyncWebhookEndpoints(AsyncResource):
    """Async twin of :class:`WebhookEndpoints`."""

    async def list(self) -> builtins.list[WebhookEndpoint]:
        """List every webhook endpoint on the workspace."""
        response = await self._client.request(RequestSpec(method="GET", path=_COLLECTION))
        return parse_model(WebhookEndpointList, response).data

    async def create(
        self, *, url: str, event_types: Sequence[WebhookEventType]
    ) -> WebhookEndpointCreated:
        """Create an endpoint and receive its show-once signing secret."""
        response = await self._client.request(
            RequestSpec(
                method="POST",
                path=_COLLECTION,
                json_body={"url": url, "event_types": list(event_types)},
            )
        )
        return parse_model(WebhookEndpointCreated, response)

    async def update(
        self,
        endpoint_id: str,
        *,
        url: Union[str, NotGiven] = NOT_GIVEN,
        event_types: Union[Sequence[WebhookEventType], NotGiven] = NOT_GIVEN,
        enabled: Union[bool, NotGiven] = NOT_GIVEN,
    ) -> WebhookEndpoint:
        """Partially update an endpoint."""
        response = await self._client.request(
            RequestSpec(
                method="PATCH",
                path=_item(endpoint_id),
                json_body=_update_body(url, event_types, enabled),
            )
        )
        return parse_model(WebhookEndpoint, response)

    async def delete(self, endpoint_id: str) -> DeleteWebhookEndpointResponse:
        """Delete an endpoint."""
        response = await self._client.request(RequestSpec(method="DELETE", path=_item(endpoint_id)))
        return parse_model(DeleteWebhookEndpointResponse, response)

    async def test(self, endpoint_id: str) -> TestWebhookEndpointResult:
        """Send a synthetic ``webhook.test`` delivery."""
        response = await self._client.request(
            RequestSpec(method="POST", path=f"{_item(endpoint_id)}/test")
        )
        return parse_model(TestWebhookEndpointResult, response)
