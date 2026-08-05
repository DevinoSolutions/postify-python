"""The SDK's operation map — the other half of the OpenAPI parity gate.

``spec/v1.json`` is vendored from the app repo and is the authoritative list of
what ``/v1`` exposes. This module is the authoritative list of what the SDK
*implements*. ``tests/unit/test_openapi_parity.py`` asserts the two sets are
identical in both directions and that every entry below resolves to a real
method on both ``Postify`` and ``AsyncPostify``.

Adding an operation server-side therefore breaks CI here until the SDK grows the
matching method — which is exactly the guarantee a code generator would give,
without the generated code.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["OPERATIONS", "Operation"]


@dataclass(frozen=True)
class Operation:
    """One ``/v1`` operation and the SDK method that implements it."""

    operation_id: str
    method: str
    path: str
    resource: str
    method_name: str
    scopes: tuple[str, ...]
    success_status: int
    paginated: bool = False
    idempotent: bool = False
    dangerous: bool = False


OPERATIONS: tuple[Operation, ...] = (
    Operation(
        operation_id="listChannels",
        method="GET",
        path="/v1/channels",
        resource="channels",
        method_name="list",
        scopes=("channels:read",),
        success_status=200,
    ),
    Operation(
        operation_id="listPosts",
        method="GET",
        path="/v1/posts",
        resource="posts",
        method_name="list",
        scopes=("posts:read",),
        success_status=200,
        paginated=True,
    ),
    Operation(
        operation_id="createPost",
        method="POST",
        path="/v1/posts",
        resource="posts",
        method_name="create",
        scopes=("posts:write",),
        success_status=201,
        idempotent=True,
        # Only the publish_now mode needs the workspace dangerous-ops toggle.
        dangerous=True,
    ),
    Operation(
        operation_id="getPost",
        method="GET",
        path="/v1/posts/{id}",
        resource="posts",
        method_name="get",
        scopes=("posts:read",),
        success_status=200,
    ),
    Operation(
        operation_id="reschedulePost",
        method="PATCH",
        path="/v1/posts/{id}",
        resource="posts",
        method_name="reschedule",
        scopes=("posts:write",),
        success_status=200,
    ),
    Operation(
        operation_id="deletePost",
        method="DELETE",
        path="/v1/posts/{id}",
        resource="posts",
        method_name="delete",
        scopes=("posts:write",),
        success_status=200,
        dangerous=True,
    ),
    Operation(
        operation_id="publishPost",
        method="POST",
        path="/v1/posts/{id}/publish",
        resource="posts",
        method_name="publish",
        scopes=("posts:write",),
        success_status=202,
        dangerous=True,
    ),
    # Media rides the posts:* scopes — there is no media:* scope in the product.
    Operation(
        operation_id="listMedia",
        method="GET",
        path="/v1/media",
        resource="media",
        method_name="list",
        scopes=("posts:read",),
        success_status=200,
        paginated=True,
    ),
    Operation(
        operation_id="createMediaUpload",
        method="POST",
        path="/v1/media/uploads",
        resource="media",
        method_name="create_upload",
        scopes=("posts:write",),
        success_status=201,
    ),
    Operation(
        operation_id="completeMediaUpload",
        method="POST",
        path="/v1/media/uploads/{id}/complete",
        resource="media",
        method_name="complete_upload",
        scopes=("posts:write",),
        success_status=200,
    ),
    Operation(
        operation_id="getAnalytics",
        method="GET",
        path="/v1/analytics",
        resource="analytics",
        method_name="get",
        scopes=("analytics:read",),
        success_status=200,
    ),
    # Usage rides analytics:read — there is no usage:read scope.
    Operation(
        operation_id="getUsage",
        method="GET",
        path="/v1/usage",
        resource="usage",
        method_name="get",
        scopes=("analytics:read",),
        success_status=200,
    ),
    Operation(
        operation_id="listWebhookEndpoints",
        method="GET",
        path="/v1/webhook-endpoints",
        resource="webhook_endpoints",
        method_name="list",
        scopes=("webhooks:read",),
        success_status=200,
    ),
    Operation(
        operation_id="createWebhookEndpoint",
        method="POST",
        path="/v1/webhook-endpoints",
        resource="webhook_endpoints",
        method_name="create",
        scopes=("webhooks:write",),
        success_status=201,
    ),
    Operation(
        operation_id="updateWebhookEndpoint",
        method="PATCH",
        path="/v1/webhook-endpoints/{id}",
        resource="webhook_endpoints",
        method_name="update",
        scopes=("webhooks:write",),
        success_status=200,
    ),
    Operation(
        operation_id="deleteWebhookEndpoint",
        method="DELETE",
        path="/v1/webhook-endpoints/{id}",
        resource="webhook_endpoints",
        method_name="delete",
        scopes=("webhooks:write",),
        success_status=200,
    ),
    Operation(
        operation_id="testWebhookEndpoint",
        method="POST",
        path="/v1/webhook-endpoints/{id}/test",
        resource="webhook_endpoints",
        method_name="test",
        scopes=("webhooks:write",),
        success_status=200,
    ),
)
