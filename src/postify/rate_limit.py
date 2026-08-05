"""Rate-limit header parsing.

Postify emits **two** generations of rate-limit headers on every API-key
response (``apps/web/src/lib/public-api/rate-limit-headers.ts``):

* IETF draft-11 structured fields::

      RateLimit-Policy: "per-key-minute";q=120;w=60
      RateLimit:        "per-key-minute";r=73;t=38

* the de-facto ``X-`` trio, where ``reset`` is a Unix epoch in **seconds**::

      X-RateLimit-Limit / X-RateLimit-Remaining / X-RateLimit-Reset

The server's honesty rule is mirrored here verbatim: **unknown values are
omitted, never invented.** A response carrying only ``RateLimit-Policy`` and
``X-RateLimit-Limit`` means "the window state was not observable on this
request" — it does *not* mean ``remaining == limit``. Every field this module
cannot read stays ``None``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

__all__ = ["RateLimitState", "parse_rate_limit"]

_QUOTED_POLICY = re.compile(r'^\s*"([^"]*)"\s*(.*)$')


@dataclass(frozen=True)
class RateLimitState:
    """A snapshot of the caller's rate-limit window, as far as it is observable.

    Attributes:
        policy: Wire name of the window, e.g. ``"per-key-minute"``. ``None``
            when only the legacy ``X-`` headers were present.
        limit: Requests permitted per window (draft-11 ``q``).
        window_sec: Window length in seconds (draft-11 ``w``).
        remaining: Requests left in the current window (draft-11 ``r``).
            ``None`` means "not observable", never "full".
        reset_at: When the window resets, timezone-aware UTC. ``None`` when the
            server did not report it.
    """

    policy: Optional[str] = None
    limit: Optional[int] = None
    window_sec: Optional[int] = None
    remaining: Optional[int] = None
    reset_at: Optional[datetime] = None

    def seconds_until_reset(self, now: Optional[datetime] = None) -> Optional[float]:
        """Seconds until ``reset_at``, floored at 0, or ``None`` if unknown."""
        if self.reset_at is None:
            return None
        current = now or datetime.now(timezone.utc)
        return max(0.0, (self.reset_at - current).total_seconds())


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_structured(value: str) -> tuple[Optional[str], dict[str, int]]:
    """Parse one draft-11 structured-field member: ``"name";k=v;k=v``."""
    first = value.split(",")[0]
    match = _QUOTED_POLICY.match(first)
    if match:
        name: Optional[str] = match.group(1)
        rest = match.group(2)
    else:
        name = None
        rest = first
    params: dict[str, int] = {}
    for chunk in rest.split(";"):
        if "=" not in chunk:
            continue
        key, _, raw = chunk.partition("=")
        parsed = _parse_int(raw)
        if parsed is not None:
            params[key.strip().lower()] = parsed
    return name, params


def parse_rate_limit(
    headers: Mapping[str, str], now: Optional[datetime] = None
) -> Optional[RateLimitState]:
    """Build a :class:`RateLimitState` from response headers.

    Returns ``None`` when the response carried no rate-limit information at all
    (for example the unauthenticated ``/v1/openapi.json`` endpoint).
    """
    current = now or datetime.now(timezone.utc)

    def get(name: str) -> Optional[str]:
        # httpx.Headers is already case-insensitive; plain dicts may not be.
        value = headers.get(name)
        if value is not None:
            return value
        lowered = name.lower()
        for key, candidate in headers.items():
            if key.lower() == lowered:
                return candidate
        return None

    policy: Optional[str] = None
    limit: Optional[int] = None
    window_sec: Optional[int] = None
    remaining: Optional[int] = None
    reset_at: Optional[datetime] = None

    policy_header = get("RateLimit-Policy")
    if policy_header:
        policy, params = _parse_structured(policy_header)
        limit = params.get("q")
        window_sec = params.get("w")

    state_header = get("RateLimit")
    if state_header:
        name, params = _parse_structured(state_header)
        policy = policy or name
        if "r" in params:
            remaining = params["r"]
        if "t" in params:
            reset_at = current + timedelta(seconds=params["t"])

    # Legacy X- trio: only fills gaps, never overrides draft-11 values.
    if limit is None:
        limit = _parse_int(get("X-RateLimit-Limit"))
    if remaining is None:
        remaining = _parse_int(get("X-RateLimit-Remaining"))
    if reset_at is None:
        reset_epoch = _parse_int(get("X-RateLimit-Reset"))
        if reset_epoch is not None:
            reset_at = datetime.fromtimestamp(reset_epoch, tz=timezone.utc)

    if policy is None and limit is None and remaining is None and reset_at is None:
        return None
    return RateLimitState(
        policy=policy,
        limit=limit,
        window_sec=window_sec,
        remaining=remaining,
        reset_at=reset_at,
    )
