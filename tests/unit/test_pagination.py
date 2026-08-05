"""Keyset pagination: auto-iteration, page walking, and filter carry-forward."""

from __future__ import annotations

import httpx
import respx

from postify import AsyncPostify, Postify

from .conftest import API_KEY, BASE_URL, media_page, post_page


@respx.mock
def test_iterating_a_pager_walks_every_page(client: Postify) -> None:
    respx.get(f"{BASE_URL}/v1/posts").mock(
        side_effect=[
            httpx.Response(
                200, json=post_page(["pst_1", "pst_2"], has_more=True, next_cursor="cur_2")
            ),
            httpx.Response(200, json=post_page(["pst_3"], has_more=False, next_cursor=None)),
        ]
    )
    ids = [post.id for post in client.posts.list()]
    assert ids == ["pst_1", "pst_2", "pst_3"]


@respx.mock
def test_filters_are_carried_forward_verbatim_onto_page_two(client: Postify) -> None:
    route = respx.get(f"{BASE_URL}/v1/posts").mock(
        side_effect=[
            httpx.Response(200, json=post_page(["pst_1"], has_more=True, next_cursor="cur_2")),
            httpx.Response(200, json=post_page(["pst_2"])),
        ]
    )
    list(client.posts.list(status="scheduled", limit=25))

    first, second = (call.request.url.params for call in route.calls)
    assert dict(first) == {"status": "scheduled", "limit": "25"}
    assert dict(second) == {"status": "scheduled", "limit": "25", "after": "cur_2"}


@respx.mock
def test_a_single_page_result_never_issues_a_second_request(client: Postify) -> None:
    route = respx.get(f"{BASE_URL}/v1/posts").mock(
        return_value=httpx.Response(200, json=post_page(["pst_1"]))
    )
    assert len(list(client.posts.list())) == 1
    assert route.call_count == 1


@respx.mock
def test_an_empty_page_iterates_zero_times(client: Postify) -> None:
    respx.get(f"{BASE_URL}/v1/posts").mock(return_value=httpx.Response(200, json=post_page([])))
    assert list(client.posts.list()) == []


@respx.mock
def test_get_next_page_returns_none_when_has_more_is_false(client: Postify) -> None:
    respx.get(f"{BASE_URL}/v1/posts").mock(
        return_value=httpx.Response(200, json=post_page(["pst_1"], has_more=False))
    )
    page = client.posts.list().first_page()
    assert page.has_more is False
    assert page.get_next_page() is None
    assert len(page) == 1
    assert [item.id for item in page] == ["pst_1"]


@respx.mock
def test_get_next_page_returns_none_when_the_cursor_is_missing(client: Postify) -> None:
    respx.get(f"{BASE_URL}/v1/posts").mock(
        return_value=httpx.Response(200, json=post_page(["pst_1"], has_more=True, next_cursor=None))
    )
    assert client.posts.list().first_page().get_next_page() is None


@respx.mock
def test_pages_expose_the_cursor_and_request_id(client: Postify) -> None:
    respx.get(f"{BASE_URL}/v1/posts").mock(
        return_value=httpx.Response(
            200,
            json=post_page(["pst_1"], has_more=True, next_cursor="cur_2"),
            headers={"Request-Id": "req_page_1"},
        )
    )
    page = client.posts.list().first_page()
    assert page.next_cursor == "cur_2"
    assert page.request_id == "req_page_1"
    assert "has_more=True" in repr(page)


@respx.mock
def test_iter_pages_yields_page_objects(client: Postify) -> None:
    respx.get(f"{BASE_URL}/v1/posts").mock(
        side_effect=[
            httpx.Response(200, json=post_page(["pst_1"], has_more=True, next_cursor="c2")),
            httpx.Response(200, json=post_page(["pst_2"])),
        ]
    )
    pages = list(client.posts.list().iter_pages())
    assert [len(page.data) for page in pages] == [1, 1]


@respx.mock
def test_an_explicit_starting_cursor_is_sent_on_the_first_request(client: Postify) -> None:
    route = respx.get(f"{BASE_URL}/v1/posts").mock(
        return_value=httpx.Response(200, json=post_page(["pst_9"]))
    )
    list(client.posts.list(after="cur_resume"))
    assert route.calls[0].request.url.params["after"] == "cur_resume"


@respx.mock
def test_media_list_paginates_the_same_way(client: Postify) -> None:
    respx.get(f"{BASE_URL}/v1/media").mock(
        side_effect=[
            httpx.Response(200, json=media_page(["ast_1"], has_more=True, next_cursor="c2")),
            httpx.Response(200, json=media_page(["ast_2"])),
        ]
    )
    assert [asset.id for asset in client.media.list()] == ["ast_1", "ast_2"]


@respx.mock
async def test_the_async_pager_reaches_the_same_items() -> None:
    respx.get(f"{BASE_URL}/v1/posts").mock(
        side_effect=[
            httpx.Response(200, json=post_page(["pst_1"], has_more=True, next_cursor="c2")),
            httpx.Response(200, json=post_page(["pst_2"])),
        ]
    )
    async with AsyncPostify(api_key=API_KEY, base_url=BASE_URL) as client:
        seen = [post.id async for post in client.posts.list()]
    assert seen == ["pst_1", "pst_2"]


@respx.mock
async def test_the_async_pager_walks_pages_manually_too() -> None:
    respx.get(f"{BASE_URL}/v1/media").mock(
        side_effect=[
            httpx.Response(200, json=media_page(["ast_1"], has_more=True, next_cursor="c2")),
            httpx.Response(200, json=media_page(["ast_2"])),
        ]
    )
    async with AsyncPostify(api_key=API_KEY, base_url=BASE_URL) as client:
        page = await client.media.list(limit=1).first_page()
        assert page.has_more is True
        nxt = await page.get_next_page()
        assert nxt is not None
        assert nxt.data[0].id == "ast_2"
        assert await nxt.get_next_page() is None


@respx.mock
def test_channels_and_webhook_endpoints_are_plain_lists_not_pagers(
    client: Postify,
) -> None:
    respx.get(f"{BASE_URL}/v1/channels").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(f"{BASE_URL}/v1/webhook-endpoints").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    assert isinstance(client.channels.list(), list)
    assert isinstance(client.webhook_endpoints.list(), list)
