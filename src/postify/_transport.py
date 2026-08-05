"""Transport policy — one implementation, two faces.

Everything that *decides* something lives here as a **pure function** over
``(request spec, outcome, attempt)``: header construction, ``Retry-After``
parsing, the retry decision, and the backoff delay. ``_client.py`` then has two
thin drivers around these — one sync, one async — that must stay diffable by
eye. No retry logic is ever duplicated between them.
"""

from __future__ import annotations

import email.utils
import platform
import random
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from ._constants import (
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    SAFE_METHODS,
    redact_api_key,
)

#: Response header echoing the correlation id of every ``/v1`` response.
REQUEST_ID_HEADER = "Request-Id"

#: Present and ``"true"`` when the server replayed a stored idempotent response.
IDEMPOTENCY_REPLAYED_HEADER = "Idempotency-Replayed"

#: A ``Retry-After`` longer than this is not worth sleeping through inside a
#: client call — the error surfaces instead so the caller can schedule properly.
MAX_RETRY_WAIT = 60.0


def user_agent(version: str) -> str:
    """``postify-python/0.1.0 httpx/0.28.1 python/3.13``."""
    py = ".".join(str(part) for part in sys.version_info[:2])
    return (
        f"postify-python/{version} httpx/{httpx.__version__} "
        f"python/{py} ({platform.system() or 'unknown'})"
    )


@dataclass
class RequestSpec:
    """Everything needed to issue one HTTP attempt, plus its retry eligibility."""

    method: str
    path: str
    params: Optional[dict[str, Any]] = None
    json_body: Optional[Any] = None
    content: Optional[bytes] = None
    headers: dict[str, str] = field(default_factory=dict)
    idempotency_key: Optional[str] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None

    @property
    def is_mutating(self) -> bool:
        return self.method.upper() not in SAFE_METHODS

    @property
    def is_retryable(self) -> bool:
        """Safe methods always; mutations **only** when they carry an idempotency key.

        This is the hard rule that keeps the SDK from silently double-firing a
        publish: an unkeyed mutation is never retried, no matter what went wrong.
        """
        return (not self.is_mutating) or bool(self.idempotency_key)


def build_headers(
    *,
    api_key: str,
    auth_style: str,
    version: str,
    default_headers: Optional[Mapping[str, str]] = None,
    extra_headers: Optional[Mapping[str, str]] = None,
    idempotency_key: Optional[str] = None,
    request_id: Optional[str] = None,
    has_json_body: bool = False,
) -> dict[str, str]:
    """Assemble the outgoing header set for one request.

    Authentication is applied **last** so a stray ``default_headers`` entry can
    never silently unauthenticate (or mis-authenticate) a request.
    """
    headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": user_agent(version),
    }
    if has_json_body:
        headers["Content-Type"] = "application/json"
    for source in (default_headers, extra_headers):
        if source:
            headers.update({str(k): str(v) for k, v in source.items() if v is not None})
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if request_id:
        headers["x-request-id"] = request_id

    if auth_style == "header":
        headers.pop("Authorization", None)
        headers["x-api-key"] = api_key
    else:
        headers.pop("x-api-key", None)
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def redacted_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Header dict safe to log — credentials replaced by their redacted form."""
    safe: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered == "authorization":
            token = value[7:] if value.lower().startswith("bearer ") else value
            safe[key] = f"Bearer {redact_api_key(token)}"
        elif lowered == "x-api-key":
            safe[key] = redact_api_key(value)
        else:
            safe[key] = value
    return safe


def parse_retry_after(value: Optional[str], now_epoch: Optional[float] = None) -> Optional[float]:
    """Parse ``Retry-After`` in both delta-seconds and HTTP-date forms."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return max(0.0, float(int(raw)))
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        from datetime import timezone

        parsed = parsed.replace(tzinfo=timezone.utc)
    import time as _time

    current = now_epoch if now_epoch is not None else _time.time()
    return max(0.0, parsed.timestamp() - current)


def should_retry(
    *,
    attempt: int,
    max_retries: int,
    retryable_request: bool,
    is_connection_error: bool = False,
    status: Optional[int] = None,
    code: Optional[str] = None,
    retry_after_seconds: Optional[float] = None,
    max_retry_wait: float = MAX_RETRY_WAIT,
) -> bool:
    """Decide whether attempt ``attempt`` (0-based) should be retried.

    The full policy, in one place:

    ==================================================  =======
    Condition                                           Retry?
    ==================================================  =======
    Connection/timeout error on a retryable request     yes
    Anything at all on an **unkeyed mutation**          no
    408 Request Timeout                                 yes
    409 ``idempotency_in_progress``                     yes
    409 anything else                                   no
    429 ``quota_exhausted``                             no
    429 (``rate_limited`` or unknown code)              yes
    5xx                                                 yes
    every other 4xx                                     no
    ``Retry-After`` longer than ``max_retry_wait``      no
    ==================================================  =======
    """
    if max_retries <= 0 or attempt >= max_retries:
        return False
    if not retryable_request:
        return False
    if retry_after_seconds is not None and retry_after_seconds > max_retry_wait:
        return False
    if is_connection_error:
        return True
    if status is None:
        return False
    if status == 408:
        return True
    if status == 409:
        return code == "idempotency_in_progress"
    if status == 429:
        return code != "quota_exhausted"
    return status >= 500


def next_delay(
    *,
    attempt: int,
    retry_after_seconds: Optional[float] = None,
    rate_limit_reset_seconds: Optional[float] = None,
    base: float = RETRY_BASE_DELAY,
    cap: float = RETRY_MAX_DELAY,
    jitter: Optional[Any] = None,
) -> float:
    """Seconds to sleep before the next attempt.

    A server-supplied ``Retry-After`` always wins; then the draft-11 ``t`` value
    from the ``RateLimit`` header; otherwise full-jitter exponential backoff
    (``uniform(0, min(cap, base * 2 ** attempt))``).
    """
    if retry_after_seconds is not None:
        return max(0.0, retry_after_seconds)
    if rate_limit_reset_seconds is not None:
        return max(0.0, min(rate_limit_reset_seconds, cap))
    ceiling = min(cap, base * (2**attempt))
    rng = jitter if jitter is not None else random.uniform
    return float(rng(0.0, ceiling))


def response_request_id(headers: Mapping[str, str]) -> Optional[str]:
    """Read the ``Request-Id`` correlation header off a response."""
    value = headers.get(REQUEST_ID_HEADER)
    if value is not None:
        return value
    for key, candidate in headers.items():
        if key.lower() == REQUEST_ID_HEADER.lower():
            return candidate
    return None


def response_idempotency_replayed(headers: Mapping[str, str]) -> bool:
    """True when the server replayed a stored response for this idempotency key."""
    value = headers.get(IDEMPOTENCY_REPLAYED_HEADER)
    if value is None:
        for key, candidate in headers.items():
            if key.lower() == IDEMPOTENCY_REPLAYED_HEADER.lower():
                value = candidate
                break
    return str(value).strip().lower() == "true" if value is not None else False
