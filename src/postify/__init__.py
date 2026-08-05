"""Official Python SDK for the Postify API (https://app.usepostify.com/v1).

Quickstart::

    import os
    from postify import Postify

    with Postify(api_key=os.environ["POSTIFY_API_KEY"]) as client:
        for channel in client.channels.list():
            print(channel.id, channel.platform, channel.handle)

Everything the API surface guarantees is a first-class object here: RFC 9457
problems map to a typed exception hierarchy, keyset cursors become
auto-paginating iterators, idempotency keys are generated for you on
``posts.create``, and rate-limit headers are parsed into
``client.last_rate_limit`` without ever inventing a value the server did not send.
"""

from __future__ import annotations

__version__ = "0.1.0"

from ._client import APIResponse, AsyncPostify, Postify
from ._constants import (
    API_KEY_ENV_VAR,
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    redact_api_key,
)
from ._registry import OPERATIONS, Operation
from ._types import NOT_GIVEN, NotGiven
from .errors import (
    PROBLEM_CODES,
    PROBLEM_TYPE_BASE,
    APIConnectionError,
    APIError,
    APITimeoutError,
    APIUserAbortError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    FieldError,
    InternalServerError,
    KnownProblemCode,
    NotFoundError,
    PermissionDeniedError,
    PostifyError,
    ProblemCode,
    RateLimitError,
    UnprocessableEntityError,
    WebhookVerificationError,
    WebhookVerificationReason,
    problem_type_uri,
)
from .models import (
    CHANNEL_STATUSES,
    MEDIA_KINDS,
    MEDIA_STATUSES,
    PLATFORMS,
    POST_DELIVERY_STAGES,
    POST_STATUSES,
    POST_TYPES,
    USAGE_METERS,
    WEBHOOK_EVENT_TYPES,
    Analytics,
    AnalyticsDelivery,
    AnalyticsEngagement,
    AnalyticsTimelinePoint,
    AnalyticsTotals,
    Channel,
    ChannelList,
    CreateUploadResponse,
    DeletePostResponse,
    DeleteWebhookEndpointResponse,
    Delivery,
    MediaAsset,
    MediaList,
    Post,
    PostifyModel,
    PostList,
    PostMediaItem,
    PostVariant,
    PublishPostResponse,
    TestWebhookEndpointResult,
    Usage,
    UsageMeter,
    WebhookEndpoint,
    WebhookEndpointCreated,
    WebhookEndpointList,
    WebhookEventEnvelope,
)
from .pagination import AsyncPage, AsyncPager, Page, SyncPager
from .rate_limit import RateLimitState, parse_rate_limit
from .webhooks import (
    WEBHOOK_ID_HEADER,
    WEBHOOK_SIGNATURE_HEADER,
    WEBHOOK_TIMESTAMP_HEADER,
    WEBHOOK_TOLERANCE_SEC,
    verify_webhook,
)

__all__ = [
    "API_KEY_ENV_VAR",
    "CHANNEL_STATUSES",
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_TIMEOUT",
    "MEDIA_KINDS",
    "MEDIA_STATUSES",
    "NOT_GIVEN",
    "OPERATIONS",
    "PLATFORMS",
    "POST_DELIVERY_STAGES",
    "POST_STATUSES",
    "POST_TYPES",
    "PROBLEM_CODES",
    "PROBLEM_TYPE_BASE",
    "USAGE_METERS",
    "WEBHOOK_EVENT_TYPES",
    "WEBHOOK_ID_HEADER",
    "WEBHOOK_SIGNATURE_HEADER",
    "WEBHOOK_TIMESTAMP_HEADER",
    "WEBHOOK_TOLERANCE_SEC",
    "APIConnectionError",
    "APIError",
    "APIResponse",
    "APITimeoutError",
    "APIUserAbortError",
    "Analytics",
    "AnalyticsDelivery",
    "AnalyticsEngagement",
    "AnalyticsTimelinePoint",
    "AnalyticsTotals",
    "AsyncPage",
    "AsyncPager",
    "AsyncPostify",
    "AuthenticationError",
    "BadRequestError",
    "Channel",
    "ChannelList",
    "ConflictError",
    "CreateUploadResponse",
    "DeletePostResponse",
    "DeleteWebhookEndpointResponse",
    "Delivery",
    "FieldError",
    "InternalServerError",
    "KnownProblemCode",
    "MediaAsset",
    "MediaList",
    "NotFoundError",
    "NotGiven",
    "Operation",
    "Page",
    "PermissionDeniedError",
    "Post",
    "PostList",
    "PostMediaItem",
    "PostVariant",
    "Postify",
    "PostifyError",
    "PostifyModel",
    "ProblemCode",
    "PublishPostResponse",
    "RateLimitError",
    "RateLimitState",
    "SyncPager",
    "TestWebhookEndpointResult",
    "UnprocessableEntityError",
    "Usage",
    "UsageMeter",
    "WebhookEndpoint",
    "WebhookEndpointCreated",
    "WebhookEndpointList",
    "WebhookEventEnvelope",
    "WebhookVerificationError",
    "WebhookVerificationReason",
    "__version__",
    "parse_rate_limit",
    "problem_type_uri",
    "redact_api_key",
    "verify_webhook",
]
