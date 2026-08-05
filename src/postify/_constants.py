"""Package-wide constants and the API-key redaction helper.

Kept dependency-free so every other module (errors, transport, client) can
import it without a cycle.
"""

from __future__ import annotations

#: Production API host. Paths are appended verbatim, so this never ends in "/".
DEFAULT_BASE_URL = "https://app.usepostify.com"

#: Retries *after* the first attempt — 2 means at most 3 requests.
DEFAULT_MAX_RETRIES = 2

#: Per-attempt timeout in seconds (not a budget for the whole retry loop).
DEFAULT_TIMEOUT = 60.0

#: Environment variable read when ``api_key`` is not passed to the constructor.
API_KEY_ENV_VAR = "POSTIFY_API_KEY"

#: Base delay for full-jitter exponential backoff, in seconds.
RETRY_BASE_DELAY = 0.5

#: Ceiling for a single backoff sleep, in seconds.
RETRY_MAX_DELAY = 8.0

#: HTTP methods that never mutate server state.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def redact_api_key(api_key: str) -> str:
    """Return a log-safe rendering of an API key.

    ``postify_live_abcdefgh1234`` -> ``postify_live_…1234``. Only the last four
    characters survive, and a secret short enough that four characters would give
    most of it away is masked entirely. Every ``__repr__`` and every error message
    in this package routes keys through here.
    """
    if not api_key:
        return "<unset>"
    prefix = ""
    secret = api_key
    for known in ("postify_live_", "postify_test_"):
        if api_key.startswith(known):
            prefix = known
            secret = api_key[len(known) :]
            break
    if len(secret) <= 8:
        return f"{prefix}…"
    return f"{prefix}…{secret[-4:]}"
