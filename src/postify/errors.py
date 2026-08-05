"""Exception hierarchy for the Postify SDK.

Every non-2xx ``/v1`` response is an RFC 9457 ``application/problem+json``
document::

    {"type": "...", "title": "...", "status": 429, "detail": "...",
     "code": "rate_limited", "request_id": "req_…", "errors": [...]}

``code`` is the branch discriminant — it is a finite, **append-only** registry
(``packages/contracts/src/public-api/problems.ts``). Branch on ``err.code``,
never on ``title`` or ``detail``, and always leave a fallback branch: a code
this SDK version has never heard of must not crash your integration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional, Union

from .rate_limit import RateLimitState, parse_rate_limit

try:  # pragma: no cover - trivial import shim
    from typing import Literal
except ImportError:  # pragma: no cover
    from typing_extensions import Literal  # type: ignore[assignment]

__all__ = [
    "PROBLEM_CODES",
    "PROBLEM_TYPE_BASE",
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "APIUserAbortError",
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "FieldError",
    "InternalServerError",
    "KnownProblemCode",
    "NotFoundError",
    "PermissionDeniedError",
    "PostifyError",
    "ProblemCode",
    "RateLimitError",
    "UnprocessableEntityError",
    "WebhookVerificationError",
    "WebhookVerificationReason",
    "problem_type_uri",
]

#: Where problem ``type`` URIs resolve.
PROBLEM_TYPE_BASE = "https://usepostify.com/docs/api/problems"

KnownProblemCode = Literal[
    "invalid_request",
    "validation_failed",
    "authentication_required",
    "invalid_api_key",
    "insufficient_scope",
    "feature_not_enabled",
    "dangerous_ops_disabled",
    "resource_not_found",
    "resource_conflict",
    "idempotency_in_progress",
    "idempotency_key_reused",
    "rate_limited",
    "quota_exhausted",
    "internal_error",
]

#: Any registry code, *or* a future code this SDK version predates. Codes are
#: append-only server-side, so unknown values must degrade, never crash.
ProblemCode = Union[KnownProblemCode, str]

#: The problem-code registry mirrored from the server, so callers can render a
#: canonical title offline. Keep in sync with ``problems.ts``.
PROBLEM_CODES: dict[str, dict[str, Any]] = {
    "invalid_request": {"status": 400, "title": "Invalid request"},
    "validation_failed": {"status": 400, "title": "Request validation failed"},
    "authentication_required": {"status": 401, "title": "Authentication required"},
    "invalid_api_key": {"status": 401, "title": "Invalid API key"},
    "insufficient_scope": {
        "status": 403,
        "title": "API credential lacks the required scope",
    },
    "feature_not_enabled": {
        "status": 403,
        "title": "Feature not available on the current plan",
    },
    "dangerous_ops_disabled": {
        "status": 403,
        "title": "Dangerous AI operations are disabled for this workspace",
    },
    "resource_not_found": {"status": 404, "title": "Resource not found"},
    "resource_conflict": {
        "status": 409,
        "title": "Resource state conflicts with the request",
    },
    "idempotency_in_progress": {
        "status": 409,
        "title": "A request with this idempotency key is still in progress",
    },
    "idempotency_key_reused": {
        "status": 422,
        "title": "Idempotency key reused with a different request body",
    },
    "rate_limited": {"status": 429, "title": "Rate limit exceeded"},
    "quota_exhausted": {
        "status": 429,
        "title": "Plan quota exhausted for this billing period",
    },
    "internal_error": {"status": 500, "title": "Internal server error"},
}


def problem_type_uri(code: str) -> str:
    """``quota_exhausted`` -> the canonical docs URI for that problem class."""
    return f"{PROBLEM_TYPE_BASE}/{code.replace('_', '-')}"


@dataclass(frozen=True)
class FieldError:
    """One field-level validation failure from a ``validation_failed`` problem."""

    pointer: str
    code: str
    message: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> FieldError:
        return cls(
            pointer=str(raw.get("pointer", "")),
            code=str(raw.get("code", "")),
            message=str(raw.get("message", "")),
        )


class PostifyError(Exception):
    """Base class for every error this SDK raises."""


class APIConnectionError(PostifyError):
    """The request never produced an HTTP response (DNS, TLS, socket, reset)."""

    def __init__(
        self, message: str = "Connection error.", *, cause: Optional[BaseException] = None
    ):
        super().__init__(message)
        self.__cause__ = cause


class APITimeoutError(APIConnectionError):
    """The request exceeded the per-attempt timeout."""

    def __init__(
        self, message: str = "Request timed out.", *, cause: Optional[BaseException] = None
    ):
        super().__init__(message, cause=cause)


class APIUserAbortError(PostifyError):
    """The caller cancelled the request (``KeyboardInterrupt``/``CancelledError``)."""


class APIError(PostifyError):
    """A non-2xx response carrying an RFC 9457 problem document.

    Attributes:
        status: HTTP status code.
        code: The stable machine-readable problem code. **Branch on this.**
        problem_type: The ``type`` URI identifying the problem class.
        title: Short human summary of the problem class.
        detail: Occurrence-specific explanation. Never parse it.
        field_errors: Field-level errors (``validation_failed`` only).
        problem: The raw decoded problem document.
        request_id: Correlation id — quote it in support requests.
        headers: Response headers.
        retry_after_seconds: Parsed ``Retry-After``, if the server sent one.
        rate_limit: Parsed rate-limit window state, if observable.
    """

    def __init__(
        self,
        *,
        status: int,
        code: ProblemCode = "",
        title: str = "",
        detail: Optional[str] = None,
        problem_type: Optional[str] = None,
        request_id: Optional[str] = None,
        field_errors: Optional[list[FieldError]] = None,
        problem: Optional[dict[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        retry_after_seconds: Optional[float] = None,
        rate_limit: Optional[RateLimitState] = None,
    ) -> None:
        self.status = status
        self.code: ProblemCode = code
        self.title = title
        self.detail = detail
        self.problem_type = problem_type
        self.request_id = request_id
        self.field_errors: list[FieldError] = field_errors or []
        self.problem: dict[str, Any] = problem or {}
        self.headers: dict[str, str] = dict(headers or {})
        self.retry_after_seconds = retry_after_seconds
        self.rate_limit = rate_limit
        super().__init__(self._render())

    def _render(self) -> str:
        if self.code:
            head = f"{self.status} {self.code}: {self.title}"
        else:
            head = f"{self.status}: {self.title}"
        if self.detail:
            head = f"{head} — {self.detail}"
        if self.request_id:
            head = f"{head} (request_id: {self.request_id})"
        return head

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience
        return f"{type(self).__name__}({self._render()!r})"

    @classmethod
    def from_response(
        cls,
        *,
        status: int,
        headers: Mapping[str, str],
        body: Optional[bytes] = None,
        parsed: Optional[dict[str, Any]] = None,
        retry_after_seconds: Optional[float] = None,
    ) -> APIError:
        """Build the most specific exception class for an error response."""
        problem: dict[str, Any] = {}
        if parsed is not None:
            problem = dict(parsed)
        elif body:
            import json

            try:
                decoded = json.loads(body.decode("utf-8", "replace"))
            except ValueError:
                decoded = None
            if isinstance(decoded, dict):
                problem = decoded

        code = problem.get("code") or ""
        title = problem.get("title") or _fallback_title(code, status)
        detail = problem.get("detail")
        problem_type = problem.get("type")
        request_id = problem.get("request_id") or _header(headers, "Request-Id")
        raw_errors = problem.get("errors")
        field_errors = (
            [FieldError.from_dict(item) for item in raw_errors if isinstance(item, dict)]
            if isinstance(raw_errors, list)
            else []
        )

        error_cls = error_class_for_status(status)
        return error_cls(
            status=status,
            code=str(code),
            title=str(title),
            detail=str(detail) if detail is not None else None,
            problem_type=str(problem_type) if problem_type is not None else None,
            request_id=str(request_id) if request_id is not None else None,
            field_errors=field_errors,
            problem=problem,
            headers=dict(headers),
            retry_after_seconds=retry_after_seconds,
            rate_limit=parse_rate_limit(headers),
        )


class BadRequestError(APIError):
    """400 — ``invalid_request`` or ``validation_failed``."""


class AuthenticationError(APIError):
    """401 — ``authentication_required`` or ``invalid_api_key``."""


class PermissionDeniedError(APIError):
    """403 — ``insufficient_scope``, ``feature_not_enabled``, ``dangerous_ops_disabled``."""


class NotFoundError(APIError):
    """404 — ``resource_not_found``."""


class ConflictError(APIError):
    """409 — ``resource_conflict`` or ``idempotency_in_progress``."""


class UnprocessableEntityError(APIError):
    """422 — ``idempotency_key_reused``."""


class RateLimitError(APIError):
    """429 — ``rate_limited`` (retryable) or ``quota_exhausted`` (not retryable)."""


class InternalServerError(APIError):
    """5xx — ``internal_error``."""


_STATUS_TO_CLASS: dict[int, type[APIError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: UnprocessableEntityError,
    429: RateLimitError,
}


def error_class_for_status(status: int) -> type[APIError]:
    """Map an HTTP status to its exception class (mirrors the TS SDK)."""
    if status >= 500:
        return InternalServerError
    return _STATUS_TO_CLASS.get(status, APIError)


def _fallback_title(code: str, status: int) -> str:
    registered = PROBLEM_CODES.get(code)
    if registered:
        return str(registered["title"])
    return f"HTTP {status}"


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    value = headers.get(name)
    if value is not None:
        return value
    lowered = name.lower()
    for key, candidate in headers.items():
        if key.lower() == lowered:
            return candidate
    return None


WebhookVerificationReason = Literal[
    "missing_headers",
    "malformed_header",
    "timestamp_out_of_tolerance",
    "no_matching_signature",
]


class WebhookVerificationError(PostifyError):
    """A webhook delivery failed signature verification.

    ``reason`` is the machine-readable cause; log it, but always return the same
    generic 400 to the sender.
    """

    def __init__(self, reason: WebhookVerificationReason, message: Optional[str] = None) -> None:
        self.reason: WebhookVerificationReason = reason
        super().__init__(message or f"Webhook verification failed: {reason}")
