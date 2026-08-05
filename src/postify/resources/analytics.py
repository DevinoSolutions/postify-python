"""``/v1/analytics`` — the workspace analytics summary."""

from __future__ import annotations

from postify._transport import RequestSpec
from postify.models import Analytics as AnalyticsModel

from ._base import AsyncResource, SyncResource, parse_model

__all__ = ["Analytics", "AsyncAnalytics"]

_PATH = "/v1/analytics"


class Analytics(SyncResource):
    """Workspace-wide analytics. Scope: ``analytics:read``."""

    def get(self) -> AnalyticsModel:
        """Fetch counts, delivery health, a 14-day timeline and summed engagement.

        Example::

            analytics = client.analytics.get()
            print(analytics.totals.published, analytics.delivery.success_rate)
        """
        response = self._client.request(RequestSpec(method="GET", path=_PATH))
        return parse_model(AnalyticsModel, response)


class AsyncAnalytics(AsyncResource):
    """Async twin of :class:`Analytics`."""

    async def get(self) -> AnalyticsModel:
        """Fetch the workspace analytics summary."""
        response = await self._client.request(RequestSpec(method="GET", path=_PATH))
        return parse_model(AnalyticsModel, response)
