"""Keyset pagination over ``/v1/posts`` and ``/v1/media``.

Wire contract: query ``limit`` (1–100, default 25) plus ``after`` (an opaque
cursor); responses carry ``{data, has_more, next_cursor}``. Cursors are base64url
keyset tokens over ``(created_at DESC, id DESC)`` that embed a **fingerprint of
the filters they were minted with** — replaying a cursor against a different
query is rejected server-side as ``invalid_request``.

The pagers therefore carry the caller's original filter parameters forward
verbatim on every page fetch and only ever swap ``after``. There is no API on
this class that lets a caller hand-mix a cursor with changed filters.

Only ``posts.list`` and ``media.list`` paginate. ``channels.list`` and
``webhook_endpoints.list`` are plan-bounded and return plain lists — they are
deliberately **not** wrapped in a pager.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Iterator
from typing import (
    Any,
    Callable,
    Generic,
    Optional,
    TypeVar,
)

from .rate_limit import RateLimitState

__all__ = ["AsyncPage", "AsyncPager", "Page", "SyncPager"]

T = TypeVar("T")


class _BasePage(Generic[T]):
    """Fields shared by the sync and async page objects."""

    def __init__(
        self,
        *,
        data: list[T],
        has_more: bool,
        next_cursor: Optional[str],
        request_id: Optional[str] = None,
        rate_limit: Optional[RateLimitState] = None,
    ) -> None:
        self.data = data
        self.has_more = has_more
        self.next_cursor = next_cursor
        self.request_id = request_id
        self.rate_limit = rate_limit

    def __iter__(self) -> Iterator[T]:
        """Iterate the items **on this page only**."""
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(items={len(self.data)}, has_more={self.has_more}, "
            f"next_cursor={self.next_cursor!r})"
        )


class Page(_BasePage[T]):
    """One page of results, plus a bound fetcher for the next one."""

    def __init__(
        self,
        *,
        data: list[T],
        has_more: bool,
        next_cursor: Optional[str],
        fetch: Callable[[Optional[str]], Page[T]],
        request_id: Optional[str] = None,
        rate_limit: Optional[RateLimitState] = None,
    ) -> None:
        super().__init__(
            data=data,
            has_more=has_more,
            next_cursor=next_cursor,
            request_id=request_id,
            rate_limit=rate_limit,
        )
        self._fetch = fetch

    def get_next_page(self) -> Optional[Page[T]]:
        """Fetch the next page, or return ``None`` when this is the last one."""
        if not self.has_more or not self.next_cursor:
            return None
        return self._fetch(self.next_cursor)


class AsyncPage(_BasePage[T]):
    """One page of results from an async client."""

    def __init__(
        self,
        *,
        data: list[T],
        has_more: bool,
        next_cursor: Optional[str],
        fetch: Callable[[Optional[str]], Awaitable[AsyncPage[T]]],
        request_id: Optional[str] = None,
        rate_limit: Optional[RateLimitState] = None,
    ) -> None:
        super().__init__(
            data=data,
            has_more=has_more,
            next_cursor=next_cursor,
            request_id=request_id,
            rate_limit=rate_limit,
        )
        self._fetch = fetch

    async def get_next_page(self) -> Optional[AsyncPage[T]]:
        """Fetch the next page, or return ``None`` when this is the last one."""
        if not self.has_more or not self.next_cursor:
            return None
        return await self._fetch(self.next_cursor)


class SyncPager(Generic[T]):
    """Lazily walks every page of a keyset-paginated list endpoint.

    Iterate it directly for items::

        for post in client.posts.list(status="scheduled"):
            print(post.id)

    or step page by page::

        page = client.posts.list().first_page()
        while page is not None:
            print(len(page.data))
            page = page.get_next_page()
    """

    def __init__(
        self,
        fetch: Callable[[Optional[str]], Page[T]],
        *,
        start_cursor: Optional[str] = None,
    ) -> None:
        self._fetch = fetch
        self._start_cursor = start_cursor

    def first_page(self) -> Page[T]:
        """Fetch and return the first page."""
        return self._fetch(self._start_cursor)

    def iter_pages(self) -> Iterator[Page[T]]:
        """Yield every page, following ``next_cursor`` until exhausted."""
        page: Optional[Page[T]] = self.first_page()
        while page is not None:
            yield page
            page = page.get_next_page()

    def __iter__(self) -> Iterator[T]:
        for page in self.iter_pages():
            yield from page.data

    def __repr__(self) -> str:
        return f"SyncPager(start_cursor={self._start_cursor!r})"


class AsyncPager(Generic[T]):
    """Async twin of :class:`SyncPager`::

    async for post in aclient.posts.list(status="scheduled"):
        print(post.id)
    """

    def __init__(
        self,
        fetch: Callable[[Optional[str]], Awaitable[AsyncPage[T]]],
        *,
        start_cursor: Optional[str] = None,
    ) -> None:
        self._fetch = fetch
        self._start_cursor = start_cursor

    async def first_page(self) -> AsyncPage[T]:
        """Fetch and return the first page."""
        return await self._fetch(self._start_cursor)

    async def iter_pages(self) -> AsyncIterator[AsyncPage[T]]:
        """Yield every page, following ``next_cursor`` until exhausted."""
        page: Optional[AsyncPage[T]] = await self.first_page()
        while page is not None:
            yield page
            page = await page.get_next_page()

    async def __aiter__(self) -> AsyncIterator[T]:
        async for page in self.iter_pages():
            for item in page.data:
                yield item

    def __repr__(self) -> str:
        return f"AsyncPager(start_cursor={self._start_cursor!r})"


def build_query(params: dict[str, Any], cursor: Optional[str] = None) -> dict[str, Any]:
    """Carry the caller's filters forward verbatim, swapping only ``after``."""
    query = {key: value for key, value in params.items() if value is not None and key != "after"}
    if cursor:
        query["after"] = cursor
    return query
