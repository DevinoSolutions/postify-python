"""Shared plumbing for the resource classes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, TypeVar

from postify._client import APIResponse
from postify.models import PostifyModel, attach_response_metadata

if TYPE_CHECKING:  # pragma: no cover
    from postify._client import AsyncPostify, Postify

M = TypeVar("M", bound=PostifyModel)

__all__ = ["AsyncResource", "SyncResource", "parse_model"]


def parse_model(model_cls: type[M], response: APIResponse) -> M:
    """Validate a decoded response body and stamp the transport metadata on it."""
    model = model_cls.model_validate(response.data if response.data is not None else {})
    attach_response_metadata(
        model,
        request_id=response.request_id,
        idempotency_replayed=response.idempotency_replayed,
        rate_limit=response.rate_limit,
    )
    return model


def prune(body: dict[str, Any]) -> dict[str, Any]:
    """Drop keys the caller never mentioned, so PATCH bodies stay partial."""
    from postify._types import given

    return {key: value for key, value in body.items() if given(value)}


class SyncResource:
    """Base class for the synchronous resource namespaces."""

    def __init__(self, client: Postify) -> None:
        self._client = client


class AsyncResource:
    """Base class for the asynchronous resource namespaces."""

    def __init__(self, client: AsyncPostify) -> None:
        self._client = client


def require_id(value: Optional[str], name: str = "id") -> str:
    """Reject empty path parameters before they become a confusing 404."""
    if not value or not str(value).strip():
        raise ValueError(f"{name} must be a non-empty string")
    return str(value)
