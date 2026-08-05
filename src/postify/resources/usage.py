"""``/v1/usage`` — the organization's plan meters.

Rides the ``analytics:read`` scope: there is no ``usage:read`` scope in the
product's scope registry. Watching the ``api_requests`` meter lets an
integration stay under its ceiling instead of discovering it via 429s.
"""

from __future__ import annotations

from postify._transport import RequestSpec
from postify.models import Usage as UsageModel

from ._base import AsyncResource, SyncResource, parse_model

__all__ = ["AsyncUsage", "Usage"]

_PATH = "/v1/usage"


class Usage(SyncResource):
    """Plan tier and meter consumption. Scope: ``analytics:read``."""

    def get(self) -> UsageModel:
        """Fetch the current plan and every meter.

        Example::

            usage = client.usage.get()
            api = usage.meter("api_requests")
            print(api.used, api.limit)
        """
        response = self._client.request(RequestSpec(method="GET", path=_PATH))
        return parse_model(UsageModel, response)


class AsyncUsage(AsyncResource):
    """Async twin of :class:`Usage`."""

    async def get(self) -> UsageModel:
        """Fetch the current plan and every meter."""
        response = await self._client.request(RequestSpec(method="GET", path=_PATH))
        return parse_model(UsageModel, response)
