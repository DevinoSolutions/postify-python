"""Pydantic models for every ``/v1`` request and response shape.

Two deliberate design choices:

1. **Every model allows extra fields.** The Postify contracts are explicitly
   additive — new fields, new platforms, and new webhook event types ship without
   a version bump. A model that rejected unknown keys would turn a non-breaking
   server change into a client outage.
2. **Closed vocabularies are typed ``Union[Literal[...], str]``.** Editors and
   type checkers surface the known values for autocomplete, while the runtime
   still accepts a value added after this SDK release. The known values are also
   exported as plain tuples (``POST_STATUSES``, ``PLATFORMS``, …) for callers
   that want to validate exhaustively themselves.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, PrivateAttr

from .rate_limit import RateLimitState

__all__ = [
    "CHANNEL_STATUSES",
    "MEDIA_KINDS",
    "MEDIA_STATUSES",
    "PLATFORMS",
    "POST_DELIVERY_STAGES",
    "POST_STATUSES",
    "POST_TYPES",
    "USAGE_METERS",
    "WEBHOOK_EVENT_TYPES",
    "Analytics",
    "AnalyticsDelivery",
    "AnalyticsEngagement",
    "AnalyticsTimelinePoint",
    "AnalyticsTotals",
    "Channel",
    "ChannelList",
    "ChannelStatus",
    "CreateUploadResponse",
    "DeletePostResponse",
    "DeleteWebhookEndpointResponse",
    "Delivery",
    "DeliveryStage",
    "MediaAsset",
    "MediaKind",
    "MediaList",
    "MediaStatus",
    "Platform",
    "Post",
    "PostList",
    "PostMediaItem",
    "PostStatus",
    "PostType",
    "PostVariant",
    "PostifyModel",
    "PublishPostResponse",
    "TestWebhookEndpointResult",
    "Usage",
    "UsageMeter",
    "UsageMeterKey",
    "WebhookEndpoint",
    "WebhookEndpointCreated",
    "WebhookEndpointList",
    "WebhookEventEnvelope",
    "WebhookEventType",
]

# --------------------------------------------------------------------------- #
# Closed-ish vocabularies (see the module docstring for the Literal|str rule)
# --------------------------------------------------------------------------- #

PLATFORMS = (
    "x",
    "linkedin",
    "facebook",
    "instagram",
    "threads",
    "tiktok",
    "pinterest",
    "youtube",
    "bluesky",
    "reddit",
)
Platform = Union[
    Literal[
        "x",
        "linkedin",
        "facebook",
        "instagram",
        "threads",
        "tiktok",
        "pinterest",
        "youtube",
        "bluesky",
        "reddit",
    ],
    str,
]

CHANNEL_STATUSES = ("live", "reauth_required", "rate_limited", "disabled")
ChannelStatus = Union[Literal["live", "reauth_required", "rate_limited", "disabled"], str]

POST_STATUSES = (
    "draft",
    "scheduled",
    "publishing",
    "published",
    "failed",
    "needs_approval",
)
PostStatus = Union[
    Literal["draft", "scheduled", "publishing", "published", "failed", "needs_approval"], str
]

POST_TYPES = ("single", "thread", "carousel", "long")
PostType = Union[Literal["single", "thread", "carousel", "long"], str]

POST_DELIVERY_STAGES = ("queued", "signed", "sent", "acked", "indexed", "failed", "dlq")
DeliveryStage = Union[Literal["queued", "signed", "sent", "acked", "indexed", "failed", "dlq"], str]

MEDIA_KINDS = ("image", "video", "audio", "raw")
MediaKind = Union[Literal["image", "video", "audio", "raw"], str]

MEDIA_STATUSES = ("pending", "ready", "failed")
MediaStatus = Union[Literal["pending", "ready", "failed"], str]

USAGE_METERS = (
    "posts_per_month",
    "channels",
    "team_members",
    "ai_credits",
    "transcription_minutes",
    "integrations",
    "api_requests",
)
UsageMeterKey = Union[
    Literal[
        "posts_per_month",
        "channels",
        "team_members",
        "ai_credits",
        "transcription_minutes",
        "integrations",
        "api_requests",
    ],
    str,
]

WEBHOOK_EVENT_TYPES = (
    "post.published",
    "post.failed",
    "channel.connected",
    "channel.reauth_required",
    "delivery.failed",
)
WebhookEventType = Union[
    Literal[
        "post.published",
        "post.failed",
        "channel.connected",
        "channel.reauth_required",
        "delivery.failed",
        "webhook.test",
    ],
    str,
]


# --------------------------------------------------------------------------- #
# Base
# --------------------------------------------------------------------------- #


class PostifyModel(BaseModel):
    """Base for every model, carrying per-response metadata off the wire."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    _request_id: Optional[str] = PrivateAttr(default=None)
    _idempotency_replayed: bool = PrivateAttr(default=False)
    _rate_limit: Optional[RateLimitState] = PrivateAttr(default=None)

    @property
    def request_id(self) -> Optional[str]:
        """Correlation id of the response that produced this object."""
        return self._request_id

    @property
    def idempotency_replayed(self) -> bool:
        """True when the server replayed a stored response for the idempotency key."""
        return self._idempotency_replayed

    @property
    def rate_limit(self) -> Optional[RateLimitState]:
        """Rate-limit window state observed on the response, if any."""
        return self._rate_limit


def attach_response_metadata(
    model: PostifyModel,
    *,
    request_id: Optional[str] = None,
    idempotency_replayed: bool = False,
    rate_limit: Optional[RateLimitState] = None,
) -> None:
    """Stamp transport metadata onto a freshly-parsed model."""
    model._request_id = request_id
    model._idempotency_replayed = idempotency_replayed
    model._rate_limit = rate_limit


# --------------------------------------------------------------------------- #
# Channels
# --------------------------------------------------------------------------- #


class Channel(PostifyModel):
    """A connected social account."""

    id: str
    platform: Platform
    handle: str
    avatar_url: Optional[str] = None
    followers: Optional[int] = None
    status: ChannelStatus
    last_sync_at: Optional[str] = None
    last_error: Optional[str] = None
    created_at: str


class ChannelList(PostifyModel):
    """All connected channels. Not paginated — the count is plan-bounded."""

    data: list[Channel]


# --------------------------------------------------------------------------- #
# Posts
# --------------------------------------------------------------------------- #


class PostMediaItem(PostifyModel):
    """One media attachment on a post variant."""

    url: str
    type: Union[Literal["image", "video"], str]
    alt: Optional[str] = None


class PostVariant(PostifyModel):
    """Per-channel tailoring of a post."""

    id: str
    channel_id: str
    body: str
    media: list[PostMediaItem] = []


class Delivery(PostifyModel):
    """Per-channel delivery outcome of a publish."""

    channel_id: str
    stage: DeliveryStage
    external_id: Optional[str] = None
    error: Optional[str] = None


class Post(PostifyModel):
    """A post across one or more channels.

    ``status`` is the post-level lifecycle state; consult :attr:`deliveries` for
    per-channel outcomes — a ``published`` post can still contain failed channels.
    """

    id: str
    status: PostStatus
    type: PostType
    title: Optional[str] = None
    body: Optional[str] = None
    scheduled_at: Optional[str] = None
    published_at: Optional[str] = None
    created_at: str
    variants: list[PostVariant] = []
    deliveries: list[Delivery] = []


class PostList(PostifyModel):
    """One page of posts, newest first."""

    data: list[Post]
    has_more: bool
    next_cursor: Optional[str] = None


class DeletePostResponse(PostifyModel):
    """Confirmation that a post was deleted."""

    id: str
    deleted: bool


class PublishPostResponse(PostifyModel):
    """Publish accepted — delivery continues in the background."""

    id: str
    status: PostStatus


# --------------------------------------------------------------------------- #
# Media
# --------------------------------------------------------------------------- #


class MediaAsset(PostifyModel):
    """A media library asset. Only ``ready`` assets should be attached to posts."""

    id: str
    filename: str
    content_type: str
    kind: MediaKind
    status: MediaStatus
    url: Optional[str] = None
    size_bytes: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_sec: Optional[float] = None
    created_at: str


class MediaList(PostifyModel):
    """One page of media assets, newest first."""

    data: list[MediaAsset]
    has_more: bool
    next_cursor: Optional[str] = None


class CreateUploadResponse(PostifyModel):
    """Upload ticket: PUT the raw bytes to :attr:`upload_url`, then complete it.

    The PUT goes to S3-compatible storage, **not** to Postify — it must carry no
    Postify credential. Use :meth:`postify.resources.media.Media.upload` and the
    SDK handles that for you.
    """

    asset_id: str
    upload_url: str
    method: str = "PUT"
    expires_at: str


# --------------------------------------------------------------------------- #
# Analytics & usage
# --------------------------------------------------------------------------- #


class AnalyticsTotals(PostifyModel):
    """Workspace-wide counts."""

    posts: int
    published: int
    scheduled: int
    failed: int
    channels: int


class AnalyticsDelivery(PostifyModel):
    """Delivery pipeline health."""

    attempts: int
    success_rate: Optional[float] = None


class AnalyticsTimelinePoint(PostifyModel):
    """Publishes on one UTC calendar day."""

    date: str
    published: int


class AnalyticsEngagement(PostifyModel):
    """Summed platform engagement across synced posts."""

    impressions: int
    likes: int
    comments: int
    shares: int
    clicks: int


class Analytics(PostifyModel):
    """Workspace analytics summary."""

    totals: AnalyticsTotals
    delivery: AnalyticsDelivery
    timeline: list[AnalyticsTimelinePoint]
    engagement: AnalyticsEngagement


class UsageMeter(PostifyModel):
    """One plan meter. ``limit``/``remaining`` are ``None`` when unlimited."""

    key: UsageMeterKey
    used: int
    limit: Optional[int] = None
    remaining: Optional[int] = None
    period_starts_at: Optional[str] = None
    period_ends_at: Optional[str] = None


class Usage(PostifyModel):
    """Plan tier plus meter consumption."""

    plan: str
    meters: list[UsageMeter]

    def meter(self, key: str) -> Optional[UsageMeter]:
        """Return the meter with ``key``, or ``None`` when the plan has no such meter."""
        for item in self.meters:
            if item.key == key:
                return item
        return None


# --------------------------------------------------------------------------- #
# Webhook endpoints
# --------------------------------------------------------------------------- #


class WebhookEndpoint(PostifyModel):
    """An outbound webhook endpoint (subscriber)."""

    id: str
    url: str
    event_types: list[WebhookEventType]
    enabled: bool
    auto_disabled_at: Optional[str] = None
    consecutive_failures: int = 0
    created_at: str


class WebhookEndpointCreated(WebhookEndpoint):
    """A newly created endpoint plus its **show-once** signing secret."""

    signing_secret: str


class WebhookEndpointList(PostifyModel):
    """All webhook endpoints. Not paginated — bounded by the ``integrations`` quota."""

    data: list[WebhookEndpoint]


class DeleteWebhookEndpointResponse(PostifyModel):
    """Confirmation that a webhook endpoint was deleted."""

    id: str
    deleted: bool


class TestWebhookEndpointResult(PostifyModel):
    """Outcome of a synthetic ``webhook.test`` delivery, signed like a real event."""

    delivery_id: str
    succeeded: bool
    http_code: Optional[int] = None
    error: Optional[str] = None


class WebhookEventEnvelope(PostifyModel):
    """The JSON body of every webhook delivery.

    ``id`` is identical to the ``webhook-id`` header and is stable across every
    retry and replay — delivery is at-least-once, so use it as your dedup key.
    The envelope and ``data`` payloads are grandfathered camelCase.
    """

    id: str
    type: WebhookEventType
    createdAt: str  # noqa: N815 - grandfathered camelCase on the wire
    data: dict[str, Any] = {}


ChannelList.model_rebuild()
Post.model_rebuild()
PostList.model_rebuild()
MediaList.model_rebuild()
Analytics.model_rebuild()
Usage.model_rebuild()
WebhookEndpointList.model_rebuild()
