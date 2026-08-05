"""``/v1/media`` — the media library and the presigned upload flow.

Media rides the ``posts:*`` scopes; there is no ``media:*`` scope in Postify's
scope registry.

Uploading is three steps: create an upload ticket, PUT the raw bytes to the
returned presigned URL, then complete the asset. The middle step goes to
S3-compatible **storage, not to Postify** — signing it with a Postify credential
invalidates the S3 signature — so the SDK issues it on a bare HTTP client with no
Postify headers at all. :meth:`Media.upload` does all three for you.
"""

from __future__ import annotations

import mimetypes
import os
from typing import IO, Any, Optional, Union, cast

from postify._transport import RequestSpec
from postify._types import NOT_GIVEN, NotGiven, given
from postify.models import CreateUploadResponse, MediaAsset, MediaList
from postify.pagination import AsyncPage, AsyncPager, Page, SyncPager, build_query

from ._base import AsyncResource, SyncResource, parse_model, require_id

__all__ = ["AsyncMedia", "Media"]

_COLLECTION = "/v1/media"
_UPLOADS = "/v1/media/uploads"

FileSource = Union[str, "os.PathLike[str]", bytes, bytearray, IO[bytes]]


def _list_params(limit: Union[int, NotGiven], after: Optional[str]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if given(limit):
        params["limit"] = limit
    if after:
        params["after"] = after
    return params


def _upload_body(filename: str, content_type: str, size_bytes: Optional[int]) -> dict[str, Any]:
    body: dict[str, Any] = {"filename": filename, "content_type": content_type}
    if size_bytes is not None:
        body["size_bytes"] = size_bytes
    return body


def _read_source(
    source: FileSource, filename: Optional[str], content_type: Optional[str]
) -> tuple[bytes, str, str]:
    """Normalize any accepted file input to ``(bytes, filename, content_type)``."""
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
        if not filename:
            raise ValueError("filename is required when uploading raw bytes")
        name = filename
    elif isinstance(source, str):
        path = source
        with open(path, "rb") as handle:
            data = handle.read()
        name = filename or os.path.basename(path)
    elif isinstance(source, os.PathLike):
        # isinstance() erases the PathLike type parameter; the alias declares str.
        path = os.fspath(cast("os.PathLike[str]", source))
        with open(path, "rb") as handle:
            data = handle.read()
        name = filename or os.path.basename(path)
    elif hasattr(source, "read"):
        data = source.read()
        if not isinstance(data, bytes):
            raise TypeError("file objects must be opened in binary mode ('rb')")
        name = filename or os.path.basename(getattr(source, "name", "") or "")
        if not name:
            raise ValueError("filename is required when uploading a nameless file object")
    else:  # pragma: no cover - defensive
        raise TypeError(f"unsupported file source: {type(source)!r}")

    resolved_type = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    return data, name, resolved_type


class Media(SyncResource):
    """Media assets. Scopes: ``posts:read`` to list, ``posts:write`` to upload."""

    def list(
        self,
        *,
        limit: Union[int, NotGiven] = NOT_GIVEN,
        after: Optional[str] = None,
    ) -> SyncPager[MediaAsset]:
        """List media assets, newest first, as an auto-paginating iterator.

        Example::

            ready = [asset for asset in client.media.list() if asset.status == "ready"]
        """
        params = _list_params(limit, after)

        def fetch(cursor: Optional[str]) -> Page[MediaAsset]:
            response = self._client.request(
                RequestSpec(method="GET", path=_COLLECTION, params=build_query(params, cursor))
            )
            parsed = parse_model(MediaList, response)
            return Page(
                data=parsed.data,
                has_more=parsed.has_more,
                next_cursor=parsed.next_cursor,
                fetch=fetch,
                request_id=response.request_id,
                rate_limit=response.rate_limit,
            )

        return SyncPager(fetch, start_cursor=after)

    def create_upload(
        self, *, filename: str, content_type: str, size_bytes: Optional[int] = None
    ) -> CreateUploadResponse:
        """Mint an upload ticket. PUT your bytes to ``ticket.upload_url`` next."""
        response = self._client.request(
            RequestSpec(
                method="POST",
                path=_UPLOADS,
                json_body=_upload_body(filename, content_type, size_bytes),
            )
        )
        return parse_model(CreateUploadResponse, response)

    def complete_upload(self, asset_id: str) -> MediaAsset:
        """Finalize a pending asset after its presigned PUT succeeded."""
        path = f"{_UPLOADS}/{require_id(asset_id, 'asset_id')}/complete"
        response = self._client.request(RequestSpec(method="POST", path=path))
        return parse_model(MediaAsset, response)

    def upload(
        self,
        file: FileSource,
        *,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> MediaAsset:
        """Upload a file end to end: create ticket -> presigned PUT -> complete.

        Accepts a path, raw ``bytes``, or a binary file object. The presigned PUT
        carries **no** Postify credential by design.

        Example::

            asset = client.media.upload("teaser.png")
            client.posts.create(
                variants=[{
                    "channel_id": "chn_123",
                    "body": "Sneak peek",
                    "media": [{"url": asset.url, "type": "image"}],
                }],
                draft=True,
            )
        """
        data, name, resolved_type = _read_source(file, filename, content_type)
        ticket = self.create_upload(filename=name, content_type=resolved_type, size_bytes=len(data))
        self._client.put_presigned(ticket.upload_url, data, content_type=resolved_type)
        return self.complete_upload(ticket.asset_id)


class AsyncMedia(AsyncResource):
    """Async twin of :class:`Media`."""

    def list(
        self,
        *,
        limit: Union[int, NotGiven] = NOT_GIVEN,
        after: Optional[str] = None,
    ) -> AsyncPager[MediaAsset]:
        """List media assets, newest first, as an auto-paginating async iterator."""
        params = _list_params(limit, after)

        async def fetch(cursor: Optional[str]) -> AsyncPage[MediaAsset]:
            response = await self._client.request(
                RequestSpec(method="GET", path=_COLLECTION, params=build_query(params, cursor))
            )
            parsed = parse_model(MediaList, response)
            return AsyncPage(
                data=parsed.data,
                has_more=parsed.has_more,
                next_cursor=parsed.next_cursor,
                fetch=fetch,
                request_id=response.request_id,
                rate_limit=response.rate_limit,
            )

        return AsyncPager(fetch, start_cursor=after)

    async def create_upload(
        self, *, filename: str, content_type: str, size_bytes: Optional[int] = None
    ) -> CreateUploadResponse:
        """Mint an upload ticket."""
        response = await self._client.request(
            RequestSpec(
                method="POST",
                path=_UPLOADS,
                json_body=_upload_body(filename, content_type, size_bytes),
            )
        )
        return parse_model(CreateUploadResponse, response)

    async def complete_upload(self, asset_id: str) -> MediaAsset:
        """Finalize a pending asset after its presigned PUT succeeded."""
        path = f"{_UPLOADS}/{require_id(asset_id, 'asset_id')}/complete"
        response = await self._client.request(RequestSpec(method="POST", path=path))
        return parse_model(MediaAsset, response)

    async def upload(
        self,
        file: FileSource,
        *,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> MediaAsset:
        """Upload a file end to end: create ticket -> presigned PUT -> complete."""
        data, name, resolved_type = _read_source(file, filename, content_type)
        ticket = await self.create_upload(
            filename=name, content_type=resolved_type, size_bytes=len(data)
        )
        await self._client.put_presigned(ticket.upload_url, data, content_type=resolved_type)
        return await self.complete_upload(ticket.asset_id)
