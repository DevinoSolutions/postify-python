"""``/v1/posts`` — list, create, read, reschedule, delete and publish posts."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Optional, Union

from postify._transport import RequestSpec
from postify._types import NOT_GIVEN, NotGiven, given
from postify.models import (
    DeletePostResponse,
    Post,
    PostList,
    PostStatus,
    PublishPostResponse,
)
from postify.pagination import AsyncPage, AsyncPager, Page, SyncPager, build_query

from ._base import AsyncResource, SyncResource, parse_model, prune, require_id

__all__ = ["AsyncPosts", "Posts"]

_COLLECTION = "/v1/posts"


def _item(post_id: str) -> str:
    return f"/v1/posts/{require_id(post_id, 'post_id')}"


def _list_params(
    limit: Union[int, NotGiven], status: Union[PostStatus, NotGiven], after: Optional[str]
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if given(limit):
        params["limit"] = limit
    if given(status):
        params["status"] = status
    if after:
        params["after"] = after
    return params


def _create_body(
    *,
    variants: Sequence[dict[str, Any]],
    title: Union[Optional[str], NotGiven],
    body: Union[Optional[str], NotGiven],
    draft: Union[bool, NotGiven],
    scheduled_at: Union[str, NotGiven],
    publish_now: Union[bool, NotGiven],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "variants": [dict(variant) for variant in variants],
        "title": title,
        "body": body,
        "draft": draft,
        "scheduled_at": scheduled_at,
        "publish_now": publish_now,
    }
    return prune(payload)


def _resolve_idempotency_key(key: Union[str, bool, None, NotGiven]) -> Optional[str]:
    """Auto-generate a key unless the caller explicitly opts out with ``False``.

    ``createPost`` is the only idempotent operation on ``/v1``. Generating a key
    by default is what makes a retry of a create safe by construction — without
    one, a connection failure mid-create could publish twice, so an unkeyed
    mutation is never retried at all.
    """
    if key is False:
        return None
    if isinstance(key, str) and key:
        return key
    return str(uuid.uuid4())


class Posts(SyncResource):
    """Posts. Scopes: ``posts:read`` to read, ``posts:write`` to mutate."""

    def list(
        self,
        *,
        limit: Union[int, NotGiven] = NOT_GIVEN,
        status: Union[PostStatus, NotGiven] = NOT_GIVEN,
        after: Optional[str] = None,
    ) -> SyncPager[Post]:
        """List posts, newest first, as an auto-paginating iterator.

        The returned pager carries your filters forward verbatim on every page —
        cursors embed a fingerprint of the query they were minted with, so
        replaying one against a different filter set is rejected server-side.

        Example::

            for post in client.posts.list(status="scheduled"):
                print(post.id, post.scheduled_at)

            page = client.posts.list(limit=100).first_page()
            print(page.has_more, page.next_cursor)
        """
        params = _list_params(limit, status, after)

        def fetch(cursor: Optional[str]) -> Page[Post]:
            response = self._client.request(
                RequestSpec(method="GET", path=_COLLECTION, params=build_query(params, cursor))
            )
            parsed = parse_model(PostList, response)
            return Page(
                data=parsed.data,
                has_more=parsed.has_more,
                next_cursor=parsed.next_cursor,
                fetch=fetch,
                request_id=response.request_id,
                rate_limit=response.rate_limit,
            )

        return SyncPager(fetch, start_cursor=after)

    def create(
        self,
        *,
        variants: Sequence[dict[str, Any]],
        title: Union[Optional[str], NotGiven] = NOT_GIVEN,
        body: Union[Optional[str], NotGiven] = NOT_GIVEN,
        draft: Union[bool, NotGiven] = NOT_GIVEN,
        scheduled_at: Union[str, NotGiven] = NOT_GIVEN,
        publish_now: Union[bool, NotGiven] = NOT_GIVEN,
        idempotency_key: Union[str, bool, None, NotGiven] = NOT_GIVEN,
    ) -> Post:
        """Create a post. Exactly one of ``draft``, ``scheduled_at`` or ``publish_now``.

        An ``Idempotency-Key`` is generated automatically; pass one explicitly to
        replay a specific request, or ``idempotency_key=False`` to omit it (which
        also makes the request non-retryable).

        ``publish_now=True`` requires the workspace's dangerous-operations toggle
        and returns 403 ``dangerous_ops_disabled`` when it is off.

        Example::

            post = client.posts.create(
                variants=[{"channel_id": "chn_123", "body": "Shipping today."}],
                scheduled_at="2026-09-01T15:00:00Z",
            )
            print(post.id, post.idempotency_replayed)
        """
        payload = _create_body(
            variants=variants,
            title=title,
            body=body,
            draft=draft,
            scheduled_at=scheduled_at,
            publish_now=publish_now,
        )
        response = self._client.request(
            RequestSpec(
                method="POST",
                path=_COLLECTION,
                json_body=payload,
                idempotency_key=_resolve_idempotency_key(idempotency_key),
            )
        )
        return parse_model(Post, response)

    def get(self, post_id: str) -> Post:
        """Fetch one post, including per-channel ``deliveries``."""
        response = self._client.request(RequestSpec(method="GET", path=_item(post_id)))
        return parse_model(Post, response)

    def reschedule(self, post_id: str, *, scheduled_at: str) -> Post:
        """Move a scheduled post to a new future publish time (ISO-8601)."""
        response = self._client.request(
            RequestSpec(
                method="PATCH", path=_item(post_id), json_body={"scheduled_at": scheduled_at}
            )
        )
        return parse_model(Post, response)

    def delete(self, post_id: str) -> DeletePostResponse:
        """Delete a post. Not idempotent — a failed attempt is never retried."""
        response = self._client.request(RequestSpec(method="DELETE", path=_item(post_id)))
        return parse_model(DeletePostResponse, response)

    def publish(self, post_id: str) -> PublishPostResponse:
        """Publish a post immediately (202 Accepted; delivery continues async).

        Requires the workspace's dangerous-operations toggle. Poll
        :meth:`get` afterwards for per-channel ``deliveries``.
        """
        response = self._client.request(
            RequestSpec(method="POST", path=f"{_item(post_id)}/publish")
        )
        return parse_model(PublishPostResponse, response)


class AsyncPosts(AsyncResource):
    """Async twin of :class:`Posts`."""

    def list(
        self,
        *,
        limit: Union[int, NotGiven] = NOT_GIVEN,
        status: Union[PostStatus, NotGiven] = NOT_GIVEN,
        after: Optional[str] = None,
    ) -> AsyncPager[Post]:
        """List posts, newest first, as an auto-paginating async iterator.

        Example::

            async for post in aclient.posts.list(status="scheduled"):
                print(post.id)
        """
        params = _list_params(limit, status, after)

        async def fetch(cursor: Optional[str]) -> AsyncPage[Post]:
            response = await self._client.request(
                RequestSpec(method="GET", path=_COLLECTION, params=build_query(params, cursor))
            )
            parsed = parse_model(PostList, response)
            return AsyncPage(
                data=parsed.data,
                has_more=parsed.has_more,
                next_cursor=parsed.next_cursor,
                fetch=fetch,
                request_id=response.request_id,
                rate_limit=response.rate_limit,
            )

        return AsyncPager(fetch, start_cursor=after)

    async def create(
        self,
        *,
        variants: Sequence[dict[str, Any]],
        title: Union[Optional[str], NotGiven] = NOT_GIVEN,
        body: Union[Optional[str], NotGiven] = NOT_GIVEN,
        draft: Union[bool, NotGiven] = NOT_GIVEN,
        scheduled_at: Union[str, NotGiven] = NOT_GIVEN,
        publish_now: Union[bool, NotGiven] = NOT_GIVEN,
        idempotency_key: Union[str, bool, None, NotGiven] = NOT_GIVEN,
    ) -> Post:
        """Create a post (see :meth:`Posts.create`)."""
        payload = _create_body(
            variants=variants,
            title=title,
            body=body,
            draft=draft,
            scheduled_at=scheduled_at,
            publish_now=publish_now,
        )
        response = await self._client.request(
            RequestSpec(
                method="POST",
                path=_COLLECTION,
                json_body=payload,
                idempotency_key=_resolve_idempotency_key(idempotency_key),
            )
        )
        return parse_model(Post, response)

    async def get(self, post_id: str) -> Post:
        """Fetch one post, including per-channel ``deliveries``."""
        response = await self._client.request(RequestSpec(method="GET", path=_item(post_id)))
        return parse_model(Post, response)

    async def reschedule(self, post_id: str, *, scheduled_at: str) -> Post:
        """Move a scheduled post to a new future publish time (ISO-8601)."""
        response = await self._client.request(
            RequestSpec(
                method="PATCH", path=_item(post_id), json_body={"scheduled_at": scheduled_at}
            )
        )
        return parse_model(Post, response)

    async def delete(self, post_id: str) -> DeletePostResponse:
        """Delete a post. Not idempotent — a failed attempt is never retried."""
        response = await self._client.request(RequestSpec(method="DELETE", path=_item(post_id)))
        return parse_model(DeletePostResponse, response)

    async def publish(self, post_id: str) -> PublishPostResponse:
        """Publish a post immediately (202 Accepted; delivery continues async)."""
        response = await self._client.request(
            RequestSpec(method="POST", path=f"{_item(post_id)}/publish")
        )
        return parse_model(PublishPostResponse, response)
