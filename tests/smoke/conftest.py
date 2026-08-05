"""Fixtures for the production smoke suite.

Every check skips **loudly** when its credential is absent, so a fork, a
contributor's laptop, or a CI run without secrets never fails here — it reports
exactly which environment variable is missing.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from postify import Postify

PROD_BASE_URL = "https://app.usepostify.com"


def _key(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"SKIPPED: {name} is not set — prod smoke check cannot run.")
    return value


@pytest.fixture(scope="session")
def api_key() -> str:
    """A full-scope key: posts:*, channels:read, analytics:read, webhooks:*."""
    return _key("POSTIFY_API_KEY")


@pytest.fixture(scope="session")
def readonly_api_key() -> str:
    """A posts:read-only key, used to prove scope enforcement."""
    return _key("POSTIFY_API_KEY_READONLY")


@pytest.fixture
def client(api_key: str) -> Iterator[Postify]:
    with Postify(api_key=api_key, base_url=PROD_BASE_URL) as instance:
        yield instance


@pytest.fixture
def created_post_ids(client: Postify) -> Iterator[list[str]]:
    """Track every post a check creates and delete them all afterwards."""
    ids: list[str] = []
    yield ids
    for post_id in ids:
        try:
            client.posts.delete(post_id)
        except Exception as exc:  # noqa: BLE001 - cleanup must never mask a failure
            print(f"cleanup: could not delete {post_id}: {exc}")
