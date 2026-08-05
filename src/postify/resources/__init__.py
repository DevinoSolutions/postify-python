"""Resource namespaces, one module per ``/v1`` resource."""

from __future__ import annotations

from .analytics import Analytics, AsyncAnalytics
from .channels import AsyncChannels, Channels
from .media import AsyncMedia, Media
from .posts import AsyncPosts, Posts
from .usage import AsyncUsage, Usage
from .webhook_endpoints import AsyncWebhookEndpoints, WebhookEndpoints

__all__ = [
    "Analytics",
    "AsyncAnalytics",
    "AsyncChannels",
    "AsyncMedia",
    "AsyncPosts",
    "AsyncUsage",
    "AsyncWebhookEndpoints",
    "Channels",
    "Media",
    "Posts",
    "Usage",
    "WebhookEndpoints",
]
