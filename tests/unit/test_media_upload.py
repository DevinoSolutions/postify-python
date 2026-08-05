"""The presigned upload flow — above all, that the PUT carries no Postify credential."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from postify import APIError, AsyncPostify, Postify

from .conftest import API_KEY, BASE_URL, media_asset, upload_ticket

PNG = b"\x89PNG\r\n\x1a\n"
STORAGE_URL = "https://storage.example.com/bucket/ast_1"


@respx.mock
def test_the_presigned_put_carries_no_postify_credential(client: Postify) -> None:
    """Signing a presigned S3 URL with an API key invalidates the S3 signature."""
    respx.post(f"{BASE_URL}/v1/media/uploads").mock(
        return_value=httpx.Response(201, json=upload_ticket())
    )
    put = respx.put(STORAGE_URL).mock(return_value=httpx.Response(200))
    respx.post(f"{BASE_URL}/v1/media/uploads/ast_1/complete").mock(
        return_value=httpx.Response(200, json=media_asset())
    )

    client.media.upload(PNG, filename="teaser.png")

    sent = put.calls[0].request
    assert "authorization" not in sent.headers
    assert "x-api-key" not in sent.headers
    assert API_KEY not in str(dict(sent.headers))
    # It also does not inherit the SDK's own default headers.
    assert not sent.headers.get("user-agent", "").startswith("postify-python/")


@respx.mock
def test_upload_runs_create_then_put_then_complete_in_order(client: Postify) -> None:
    calls: list[str] = []

    def record(name: str, response: httpx.Response):
        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(name)
            return response

        return handler

    respx.post(f"{BASE_URL}/v1/media/uploads").mock(
        side_effect=record("create", httpx.Response(201, json=upload_ticket()))
    )
    respx.put(STORAGE_URL).mock(side_effect=record("put", httpx.Response(200)))
    respx.post(f"{BASE_URL}/v1/media/uploads/ast_1/complete").mock(
        side_effect=record("complete", httpx.Response(200, json=media_asset()))
    )

    asset = client.media.upload(PNG, filename="teaser.png")
    assert calls == ["create", "put", "complete"]
    assert asset.id == "ast_1"
    assert asset.status == "ready"


@respx.mock
def test_the_upload_ticket_request_declares_filename_type_and_size(
    client: Postify,
) -> None:
    create = respx.post(f"{BASE_URL}/v1/media/uploads").mock(
        return_value=httpx.Response(201, json=upload_ticket())
    )
    respx.put(STORAGE_URL).mock(return_value=httpx.Response(200))
    respx.post(f"{BASE_URL}/v1/media/uploads/ast_1/complete").mock(
        return_value=httpx.Response(200, json=media_asset())
    )
    client.media.upload(PNG, filename="teaser.png")
    body = json.loads(create.calls[0].request.content)
    assert body == {
        "filename": "teaser.png",
        "content_type": "image/png",
        "size_bytes": len(PNG),
    }


@respx.mock
def test_the_put_sends_the_raw_bytes_with_the_declared_content_type(
    client: Postify,
) -> None:
    respx.post(f"{BASE_URL}/v1/media/uploads").mock(
        return_value=httpx.Response(201, json=upload_ticket())
    )
    put = respx.put(STORAGE_URL).mock(return_value=httpx.Response(200))
    respx.post(f"{BASE_URL}/v1/media/uploads/ast_1/complete").mock(
        return_value=httpx.Response(200, json=media_asset())
    )
    client.media.upload(PNG, filename="teaser.png")
    assert put.calls[0].request.content == PNG
    assert put.calls[0].request.headers["content-type"] == "image/png"


@respx.mock
def test_uploading_from_a_path_infers_the_filename_and_content_type(
    client: Postify, tmp_path: Path
) -> None:
    target = tmp_path / "launch.png"
    target.write_bytes(PNG)
    create = respx.post(f"{BASE_URL}/v1/media/uploads").mock(
        return_value=httpx.Response(201, json=upload_ticket())
    )
    respx.put(STORAGE_URL).mock(return_value=httpx.Response(200))
    respx.post(f"{BASE_URL}/v1/media/uploads/ast_1/complete").mock(
        return_value=httpx.Response(200, json=media_asset())
    )
    client.media.upload(target)
    body = json.loads(create.calls[0].request.content)
    assert body["filename"] == "launch.png"
    assert body["content_type"] == "image/png"


@respx.mock
def test_uploading_from_a_binary_file_object_works(client: Postify, tmp_path: Path) -> None:
    target = tmp_path / "clip.mp4"
    target.write_bytes(PNG)
    create = respx.post(f"{BASE_URL}/v1/media/uploads").mock(
        return_value=httpx.Response(201, json=upload_ticket())
    )
    respx.put(STORAGE_URL).mock(return_value=httpx.Response(200))
    respx.post(f"{BASE_URL}/v1/media/uploads/ast_1/complete").mock(
        return_value=httpx.Response(200, json=media_asset())
    )
    with open(target, "rb") as handle:
        client.media.upload(handle)
    assert json.loads(create.calls[0].request.content)["filename"] == "clip.mp4"


def test_raw_bytes_without_a_filename_are_rejected(client: Postify) -> None:
    with pytest.raises(ValueError):
        client.media.upload(PNG)


def test_a_text_mode_file_object_is_rejected(client: Postify, tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("hello")
    with open(target) as handle, pytest.raises(TypeError):
        client.media.upload(handle)


@respx.mock
def test_a_failed_presigned_put_raises_an_api_error(client: Postify) -> None:
    respx.post(f"{BASE_URL}/v1/media/uploads").mock(
        return_value=httpx.Response(201, json=upload_ticket())
    )
    respx.put(STORAGE_URL).mock(
        return_value=httpx.Response(403, text="<Error>SignatureDoesNotMatch</Error>")
    )
    with pytest.raises(APIError) as excinfo:
        client.media.upload(PNG, filename="teaser.png")
    assert excinfo.value.status == 403
    assert "SignatureDoesNotMatch" in (excinfo.value.detail or "")


@respx.mock
def test_create_upload_and_complete_upload_can_be_driven_manually(
    client: Postify,
) -> None:
    respx.post(f"{BASE_URL}/v1/media/uploads").mock(
        return_value=httpx.Response(201, json=upload_ticket())
    )
    complete = respx.post(f"{BASE_URL}/v1/media/uploads/ast_1/complete").mock(
        return_value=httpx.Response(200, json=media_asset())
    )
    ticket = client.media.create_upload(filename="teaser.png", content_type="image/png")
    assert ticket.method == "PUT"
    assert ticket.asset_id == "ast_1"
    asset = client.media.complete_upload(ticket.asset_id)
    assert asset.url is not None
    assert complete.call_count == 1


@respx.mock
async def test_the_async_upload_is_equally_credential_free() -> None:
    respx.post(f"{BASE_URL}/v1/media/uploads").mock(
        return_value=httpx.Response(201, json=upload_ticket())
    )
    put = respx.put(STORAGE_URL).mock(return_value=httpx.Response(200))
    respx.post(f"{BASE_URL}/v1/media/uploads/ast_1/complete").mock(
        return_value=httpx.Response(200, json=media_asset())
    )
    async with AsyncPostify(api_key=API_KEY, base_url=BASE_URL) as client:
        asset = await client.media.upload(PNG, filename="teaser.png")
    assert asset.id == "ast_1"
    assert "authorization" not in put.calls[0].request.headers
