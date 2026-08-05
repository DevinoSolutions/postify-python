"""``/v1/channels`` — the connected social accounts.

Not paginated: the channel count is plan-bounded (max 50), so the endpoint
returns a plain list and this resource returns a plain ``list[Channel]``.
"""

from __future__ import annotations

import builtins

from postify._transport import RequestSpec
from postify.models import Channel, ChannelList

from ._base import AsyncResource, SyncResource, parse_model

__all__ = ["AsyncChannels", "Channels"]

_PATH = "/v1/channels"


class Channels(SyncResource):
    """Read the workspace's connected channels. Scope: ``channels:read``."""

    def list(self) -> builtins.list[Channel]:
        """List every connected channel.

        Only channels with ``status == "live"`` can publish; ``reauth_required``
        needs the owner to reconnect the account inside the Postify app.

        Example::

            for channel in client.channels.list():
                print(channel.id, channel.platform, channel.status)
        """
        response = self._client.request(RequestSpec(method="GET", path=_PATH))
        return parse_model(ChannelList, response).data


class AsyncChannels(AsyncResource):
    """Async twin of :class:`Channels`."""

    async def list(self) -> builtins.list[Channel]:
        """List every connected channel."""
        response = await self._client.request(RequestSpec(method="GET", path=_PATH))
        return parse_model(ChannelList, response).data
