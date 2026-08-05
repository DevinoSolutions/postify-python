"""The sync and async Postify clients.

Both drive the same pure policy functions from :mod:`postify._transport`. The
two request loops below are intentionally line-for-line comparable — if you
change one, change the other, and neither may grow a retry rule of its own.
"""

from __future__ import annotations

import asyncio
import json as jsonlib
import os
import time
from collections.abc import Mapping
from typing import Any, Optional, Union

import httpx

from ._constants import (
    API_KEY_ENV_VAR,
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    redact_api_key,
)
from ._transport import (
    RequestSpec,
    build_headers,
    next_delay,
    parse_retry_after,
    response_idempotency_replayed,
    response_request_id,
    should_retry,
)
from .errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    APIUserAbortError,
    PostifyError,
)
from .rate_limit import RateLimitState, parse_rate_limit

__all__ = ["APIResponse", "AsyncPostify", "Postify"]

#: Indirection so tests can observe backoff without actually sleeping.
_sleep = time.sleep
_asleep = asyncio.sleep


class APIResponse:
    """A decoded 2xx response plus the transport metadata that came with it."""

    __slots__ = ("status", "headers", "data", "request_id", "idempotency_replayed", "rate_limit")

    def __init__(
        self,
        *,
        status: int,
        headers: Mapping[str, str],
        data: Any,
        request_id: Optional[str],
        idempotency_replayed: bool,
        rate_limit: Optional[RateLimitState],
    ) -> None:
        self.status = status
        self.headers = dict(headers)
        self.data = data
        self.request_id = request_id
        self.idempotency_replayed = idempotency_replayed
        self.rate_limit = rate_limit


def _resolve_api_key(api_key: Optional[str]) -> str:
    resolved = api_key if api_key is not None else os.environ.get(API_KEY_ENV_VAR)
    if not resolved:
        raise PostifyError(
            "No API key supplied. Pass api_key=… or set the "
            f"{API_KEY_ENV_VAR} environment variable. Mint a key in "
            "Postify → Settings → API keys."
        )
    return resolved


def _decode_body(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return jsonlib.loads(response.content.decode("utf-8", "replace"))
    except ValueError:
        return None


class _BaseClient:
    """Configuration, URL building and header assembly shared by both clients."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        auth_style: str = "bearer",
        default_headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        if auth_style not in ("bearer", "header"):
            raise ValueError('auth_style must be "bearer" or "header"')
        self.api_key = _resolve_api_key(api_key)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.auth_style = auth_style
        self.default_headers: dict[str, str] = dict(default_headers or {})

        #: Rate-limit window observed on the most recent response, if any.
        self.last_rate_limit: Optional[RateLimitState] = None
        #: ``Request-Id`` of the most recent response — quote it in support tickets.
        self.last_request_id: Optional[str] = None

    # -- helpers ----------------------------------------------------------- #

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    def _headers_for(self, spec: RequestSpec) -> dict[str, str]:
        from . import __version__

        return build_headers(
            api_key=self.api_key,
            auth_style=self.auth_style,
            version=__version__,
            default_headers=self.default_headers,
            extra_headers=spec.headers,
            idempotency_key=spec.idempotency_key,
            has_json_body=spec.json_body is not None,
        )

    def _record(self, response: httpx.Response) -> tuple[Optional[str], Optional[RateLimitState]]:
        request_id = response_request_id(response.headers)
        rate_limit = parse_rate_limit(response.headers)
        if request_id:
            self.last_request_id = request_id
        if rate_limit:
            self.last_rate_limit = rate_limit
        return request_id, rate_limit

    def _retries_for(self, spec: RequestSpec) -> int:
        return self.max_retries if spec.max_retries is None else spec.max_retries

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(base_url={self.base_url!r}, "
            f"api_key={redact_api_key(self.api_key)!r}, auth_style={self.auth_style!r}, "
            f"max_retries={self.max_retries})"
        )

    __str__ = __repr__


class Postify(_BaseClient):
    """Synchronous Postify API client.

    Example::

        from postify import Postify

        with Postify(api_key="postify_live_…") as client:
            for channel in client.channels.list():
                print(channel.handle, channel.status)

    Args:
        api_key: Organization API key. Falls back to ``$POSTIFY_API_KEY``.
        base_url: API origin. Defaults to ``https://app.usepostify.com``.
        timeout: Per-attempt timeout in seconds.
        max_retries: Retries after the first attempt. ``0`` disables retrying.
        auth_style: ``"bearer"`` (default) or ``"header"`` for ``x-api-key``.
        default_headers: Extra headers sent on every request.
        http_client: Bring your own ``httpx.Client`` (proxies, mounts, limits).
            When supplied, the SDK never closes it.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        auth_style: str = "bearer",
        default_headers: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            auth_style=auth_style,
            default_headers=default_headers,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)
        self._bare_http: Optional[httpx.Client] = None

        from .resources.analytics import Analytics
        from .resources.channels import Channels
        from .resources.media import Media
        from .resources.posts import Posts
        from .resources.usage import Usage
        from .resources.webhook_endpoints import WebhookEndpoints

        self.channels: Channels = Channels(self)
        self.posts: Posts = Posts(self)
        self.media: Media = Media(self)
        self.analytics: Analytics = Analytics(self)
        self.usage: Usage = Usage(self)
        self.webhook_endpoints: WebhookEndpoints = WebhookEndpoints(self)

    # -- lifecycle --------------------------------------------------------- #

    def close(self) -> None:
        """Close the owned HTTP connection pools. Injected clients are left alone."""
        if self._bare_http is not None:
            self._bare_http.close()
            self._bare_http = None
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Postify:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # -- request loop ------------------------------------------------------ #

    def request(self, spec: RequestSpec) -> APIResponse:
        """Issue one request, applying the shared auth/retry/problem policy."""
        max_retries = self._retries_for(spec)
        attempt = 0
        while True:
            try:
                response = self._http.request(
                    spec.method,
                    self._url(spec.path),
                    params=spec.params or None,
                    json=spec.json_body,
                    content=spec.content,
                    headers=self._headers_for(spec),
                    timeout=spec.timeout if spec.timeout is not None else self.timeout,
                )
            except KeyboardInterrupt as exc:  # pragma: no cover - interactive only
                raise APIUserAbortError("Request aborted by the caller.") from exc
            except httpx.TimeoutException as exc:
                error: APIConnectionError = APITimeoutError(
                    f"Request timed out after {self.timeout}s.", cause=exc
                )
            except httpx.HTTPError as exc:
                error = APIConnectionError(f"Connection error: {exc}", cause=exc)
            else:
                request_id, rate_limit = self._record(response)
                if response.status_code < 300:
                    return APIResponse(
                        status=response.status_code,
                        headers=response.headers,
                        data=_decode_body(response),
                        request_id=request_id,
                        idempotency_replayed=response_idempotency_replayed(response.headers),
                        rate_limit=rate_limit,
                    )
                delay = _error_delay_or_raise(response, attempt, max_retries, spec, rate_limit)
                _sleep(delay)
                attempt += 1
                continue

            if should_retry(
                attempt=attempt,
                max_retries=max_retries,
                retryable_request=spec.is_retryable,
                is_connection_error=True,
            ):
                _sleep(next_delay(attempt=attempt))
                attempt += 1
                continue
            raise error

    # -- presigned upload -------------------------------------------------- #

    def put_presigned(
        self,
        url: str,
        content: bytes,
        *,
        content_type: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        """PUT raw bytes to an S3-compatible presigned URL.

        Issued on a **bare** HTTP client that carries none of this SDK's default
        headers and, critically, no Postify credential: adding ``Authorization``
        or ``x-api-key`` to a presigned request invalidates the S3 signature.
        """
        if self._bare_http is None:
            self._bare_http = httpx.Client(timeout=timeout or self.timeout)
        headers = {"Content-Type": content_type} if content_type else {}
        try:
            response = self._bare_http.put(
                url, content=content, headers=headers, timeout=timeout or self.timeout
            )
        except httpx.TimeoutException as exc:
            raise APITimeoutError("Presigned upload timed out.", cause=exc) from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError(f"Presigned upload failed: {exc}", cause=exc) from exc
        if response.status_code >= 300:
            raise APIError(
                status=response.status_code,
                code="invalid_request",
                title="Presigned upload failed",
                detail=response.text[:500] or None,
                headers=dict(response.headers),
            )


class AsyncPostify(_BaseClient):
    """Asynchronous Postify API client — the exact twin of :class:`Postify`.

    Example::

        import asyncio
        from postify import AsyncPostify

        async def main():
            async with AsyncPostify(api_key="postify_live_…") as client:
                usage = await client.usage.get()
                print(usage.plan)

        asyncio.run(main())
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        auth_style: str = "bearer",
        default_headers: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            auth_style=auth_style,
            default_headers=default_headers,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._bare_http: Optional[httpx.AsyncClient] = None

        from .resources.analytics import AsyncAnalytics
        from .resources.channels import AsyncChannels
        from .resources.media import AsyncMedia
        from .resources.posts import AsyncPosts
        from .resources.usage import AsyncUsage
        from .resources.webhook_endpoints import AsyncWebhookEndpoints

        self.channels: AsyncChannels = AsyncChannels(self)
        self.posts: AsyncPosts = AsyncPosts(self)
        self.media: AsyncMedia = AsyncMedia(self)
        self.analytics: AsyncAnalytics = AsyncAnalytics(self)
        self.usage: AsyncUsage = AsyncUsage(self)
        self.webhook_endpoints: AsyncWebhookEndpoints = AsyncWebhookEndpoints(self)

    # -- lifecycle --------------------------------------------------------- #

    async def aclose(self) -> None:
        """Close the owned HTTP connection pools. Injected clients are left alone."""
        if self._bare_http is not None:
            await self._bare_http.aclose()
            self._bare_http = None
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncPostify:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()

    # -- request loop ------------------------------------------------------ #

    async def request(self, spec: RequestSpec) -> APIResponse:
        """Issue one request, applying the shared auth/retry/problem policy."""
        max_retries = self._retries_for(spec)
        attempt = 0
        while True:
            try:
                response = await self._http.request(
                    spec.method,
                    self._url(spec.path),
                    params=spec.params or None,
                    json=spec.json_body,
                    content=spec.content,
                    headers=self._headers_for(spec),
                    timeout=spec.timeout if spec.timeout is not None else self.timeout,
                )
            except asyncio.CancelledError as exc:
                raise APIUserAbortError("Request aborted by the caller.") from exc
            except httpx.TimeoutException as exc:
                error: APIConnectionError = APITimeoutError(
                    f"Request timed out after {self.timeout}s.", cause=exc
                )
            except httpx.HTTPError as exc:
                error = APIConnectionError(f"Connection error: {exc}", cause=exc)
            else:
                request_id, rate_limit = self._record(response)
                if response.status_code < 300:
                    return APIResponse(
                        status=response.status_code,
                        headers=response.headers,
                        data=_decode_body(response),
                        request_id=request_id,
                        idempotency_replayed=response_idempotency_replayed(response.headers),
                        rate_limit=rate_limit,
                    )
                delay = _error_delay_or_raise(response, attempt, max_retries, spec, rate_limit)
                await _asleep(delay)
                attempt += 1
                continue

            if should_retry(
                attempt=attempt,
                max_retries=max_retries,
                retryable_request=spec.is_retryable,
                is_connection_error=True,
            ):
                await _asleep(next_delay(attempt=attempt))
                attempt += 1
                continue
            raise error

    # -- presigned upload -------------------------------------------------- #

    async def put_presigned(
        self,
        url: str,
        content: bytes,
        *,
        content_type: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        """PUT raw bytes to an S3-compatible presigned URL (no Postify credential)."""
        if self._bare_http is None:
            self._bare_http = httpx.AsyncClient(timeout=timeout or self.timeout)
        headers = {"Content-Type": content_type} if content_type else {}
        try:
            response = await self._bare_http.put(
                url, content=content, headers=headers, timeout=timeout or self.timeout
            )
        except httpx.TimeoutException as exc:
            raise APITimeoutError("Presigned upload timed out.", cause=exc) from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError(f"Presigned upload failed: {exc}", cause=exc) from exc
        if response.status_code >= 300:
            raise APIError(
                status=response.status_code,
                code="invalid_request",
                title="Presigned upload failed",
                detail=response.text[:500] or None,
                headers=dict(response.headers),
            )


def _error_delay_or_raise(
    response: httpx.Response,
    attempt: int,
    max_retries: int,
    spec: RequestSpec,
    rate_limit: Optional[RateLimitState],
) -> float:
    """Shared non-2xx handling: either return a retry delay, or raise.

    Both request loops call exactly this — the retry decision exists once.
    """
    body = _decode_body(response)
    problem = body if isinstance(body, dict) else {}
    code = problem.get("code")
    retry_after = parse_retry_after(response.headers.get("Retry-After"))
    if should_retry(
        attempt=attempt,
        max_retries=max_retries,
        retryable_request=spec.is_retryable,
        status=response.status_code,
        code=str(code) if code is not None else None,
        retry_after_seconds=retry_after,
    ):
        reset_seconds = (
            rate_limit.seconds_until_reset()
            if rate_limit is not None and response.status_code == 429
            else None
        )
        return next_delay(
            attempt=attempt,
            retry_after_seconds=retry_after,
            rate_limit_reset_seconds=reset_seconds,
        )
    raise APIError.from_response(
        status=response.status_code,
        headers=response.headers,
        parsed=problem,
        retry_after_seconds=retry_after,
    )


PostifyClient = Union[Postify, AsyncPostify]
