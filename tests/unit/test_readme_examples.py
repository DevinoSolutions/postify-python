"""Every ``python`` code block in the README is executed against a mocked API.

Documentation that does not run is documentation that rots. Each fenced block is
compiled and then executed in a fresh namespace with the whole ``/v1`` surface
stubbed, so a rename in the SDK breaks the README in CI rather than in a user's
terminal.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
import respx

from .conftest import (
    BASE_URL,
    analytics,
    channel,
    media_asset,
    post,
    post_page,
    upload_ticket,
    usage,
    webhook_endpoint,
)

README = Path(__file__).resolve().parents[2] / "README.md"
BLOCK = re.compile(r"^```python\n(.*?)^```", re.DOTALL | re.MULTILINE)


def readme_blocks() -> list[str]:
    return BLOCK.findall(README.read_text(encoding="utf-8"))


def install_routes(router: respx.Router) -> None:
    router.get(f"{BASE_URL}/v1/channels").mock(
        return_value=httpx.Response(200, json={"data": [channel()]})
    )
    router.get(f"{BASE_URL}/v1/posts").mock(
        return_value=httpx.Response(200, json=post_page(["pst_1"]))
    )
    router.post(f"{BASE_URL}/v1/posts").mock(return_value=httpx.Response(201, json=post()))
    router.get(url__regex=rf"{BASE_URL}/v1/posts/[^/]+$").mock(
        return_value=httpx.Response(200, json=post())
    )
    router.get(f"{BASE_URL}/v1/media").mock(
        return_value=httpx.Response(
            200, json={"data": [media_asset()], "has_more": False, "next_cursor": None}
        )
    )
    router.post(f"{BASE_URL}/v1/media/uploads").mock(
        return_value=httpx.Response(201, json=upload_ticket())
    )
    router.post(url__regex=rf"{BASE_URL}/v1/media/uploads/[^/]+/complete$").mock(
        return_value=httpx.Response(200, json=media_asset())
    )
    router.get(f"{BASE_URL}/v1/analytics").mock(return_value=httpx.Response(200, json=analytics()))
    router.get(f"{BASE_URL}/v1/usage").mock(
        return_value=httpx.Response(
            200,
            json=usage(),
            headers={
                "RateLimit-Policy": '"per-key-minute";q=120;w=60',
                "RateLimit": '"per-key-minute";r=73;t=38',
                "Request-Id": "req_readme",
            },
        )
    )
    router.get(f"{BASE_URL}/v1/webhook-endpoints").mock(
        return_value=httpx.Response(200, json={"data": [webhook_endpoint()]})
    )
    router.post(f"{BASE_URL}/v1/webhook-endpoints").mock(
        return_value=httpx.Response(
            201, json=dict(webhook_endpoint(), signing_secret="whsec_readmeexample")
        )
    )
    router.patch(url__regex=rf"{BASE_URL}/v1/webhook-endpoints/[^/]+$").mock(
        return_value=httpx.Response(200, json=webhook_endpoint(enabled=False))
    )
    router.delete(url__regex=rf"{BASE_URL}/v1/webhook-endpoints/[^/]+$").mock(
        return_value=httpx.Response(200, json={"id": "whe_1", "deleted": True})
    )
    router.post(url__regex=rf"{BASE_URL}/v1/webhook-endpoints/[^/]+/test$").mock(
        return_value=httpx.Response(
            200,
            json={"delivery_id": "dlv_1", "succeeded": True, "http_code": 200, "error": None},
        )
    )
    router.put(url__regex=r"https://storage\.example\.com/.*").mock(
        return_value=httpx.Response(200)
    )
    # Anything the README reaches that is not modelled above is a test bug.
    router.route().mock(side_effect=AssertionError("README example hit an unmocked endpoint"))


def test_the_readme_actually_contains_examples() -> None:
    assert len(readme_blocks()) >= 10


@pytest.mark.parametrize("index", range(len(readme_blocks())))
def test_each_readme_python_block_compiles(index: int) -> None:
    compile(readme_blocks()[index], f"README.md#block{index}", "exec")


@pytest.mark.parametrize("index", range(len(readme_blocks())))
def test_each_readme_python_block_runs_against_the_mocked_api(
    index: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POSTIFY_API_KEY", "postify_live_examplekey1234")
    source = readme_blocks()[index]
    with respx.mock(assert_all_called=False) as router:
        install_routes(router)
        namespace: dict = {"__name__": "__readme__"}
        exec(compile(source, f"README.md#block{index}", "exec"), namespace)  # noqa: S102
