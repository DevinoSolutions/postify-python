"""Standard Webhooks verification, including rotation and every failure reason."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

from postify import WEBHOOK_TOLERANCE_SEC, WebhookVerificationError, verify_webhook

from .conftest import WEBHOOK_SECRET, event_body, sign_webhook


def test_a_valid_delivery_verifies_and_returns_the_parsed_envelope() -> None:
    body = event_body()
    event = verify_webhook(payload=body, headers=sign_webhook(body), secret=WEBHOOK_SECRET)
    assert event.id == "evt_1"
    assert event.type == "post.published"
    assert event.data["postId"] == "pst_1"
    assert event.createdAt == "2026-08-05T12:00:00.000Z"


def test_verification_happens_over_raw_bytes_not_a_reserialized_body() -> None:
    """Re-serializing changes whitespace, and the signature must then fail."""
    body = b'{"id":"evt_1","type":"webhook.test","createdAt":"2026-08-05T12:00:00.000Z","data":{}}'
    headers = sign_webhook(body)
    assert verify_webhook(payload=body, headers=headers, secret=WEBHOOK_SECRET).id == "evt_1"

    reserialized = json.dumps(json.loads(body), indent=2).encode()
    with pytest.raises(WebhookVerificationError) as excinfo:
        verify_webhook(payload=reserialized, headers=headers, secret=WEBHOOK_SECRET)
    assert excinfo.value.reason == "no_matching_signature"


def test_a_string_payload_is_accepted_and_encoded_as_utf8() -> None:
    body = event_body()
    headers = sign_webhook(body)
    assert (
        verify_webhook(payload=body.decode(), headers=headers, secret=WEBHOOK_SECRET).id == "evt_1"
    )


def test_a_tampered_body_fails_with_no_matching_signature() -> None:
    body = event_body()
    headers = sign_webhook(body)
    with pytest.raises(WebhookVerificationError) as excinfo:
        verify_webhook(payload=body + b" ", headers=headers, secret=WEBHOOK_SECRET)
    assert excinfo.value.reason == "no_matching_signature"


def test_the_wrong_secret_fails_with_no_matching_signature() -> None:
    body = event_body()
    other = "whsec_" + base64.b64encode(b"z" * 24).decode()
    with pytest.raises(WebhookVerificationError) as excinfo:
        verify_webhook(payload=body, headers=sign_webhook(body), secret=other)
    assert excinfo.value.reason == "no_matching_signature"


def test_a_stale_timestamp_is_rejected() -> None:
    body = event_body()
    stale = int(time.time()) - (WEBHOOK_TOLERANCE_SEC + 60)
    with pytest.raises(WebhookVerificationError) as excinfo:
        verify_webhook(
            payload=body, headers=sign_webhook(body, timestamp=stale), secret=WEBHOOK_SECRET
        )
    assert excinfo.value.reason == "timestamp_out_of_tolerance"


def test_a_future_timestamp_is_rejected_too() -> None:
    body = event_body()
    ahead = int(time.time()) + (WEBHOOK_TOLERANCE_SEC + 60)
    with pytest.raises(WebhookVerificationError) as excinfo:
        verify_webhook(
            payload=body, headers=sign_webhook(body, timestamp=ahead), secret=WEBHOOK_SECRET
        )
    assert excinfo.value.reason == "timestamp_out_of_tolerance"


def test_a_timestamp_just_inside_the_tolerance_window_passes() -> None:
    body = event_body()
    edge = int(time.time()) - (WEBHOOK_TOLERANCE_SEC - 5)
    event = verify_webhook(
        payload=body, headers=sign_webhook(body, timestamp=edge), secret=WEBHOOK_SECRET
    )
    assert event.id == "evt_1"


def test_a_custom_tolerance_is_honored() -> None:
    body = event_body()
    when = int(time.time()) - 30
    with pytest.raises(WebhookVerificationError) as excinfo:
        verify_webhook(
            payload=body,
            headers=sign_webhook(body, timestamp=when),
            secret=WEBHOOK_SECRET,
            tolerance_sec=10,
        )
    assert excinfo.value.reason == "timestamp_out_of_tolerance"


@pytest.mark.parametrize("drop", ["webhook-id", "webhook-timestamp", "webhook-signature"])
def test_each_missing_header_raises_missing_headers(drop: str) -> None:
    body = event_body()
    headers = sign_webhook(body)
    del headers[drop]
    with pytest.raises(WebhookVerificationError) as excinfo:
        verify_webhook(payload=body, headers=headers, secret=WEBHOOK_SECRET)
    assert excinfo.value.reason == "missing_headers"


def test_a_non_integer_timestamp_raises_malformed_header() -> None:
    body = event_body()
    headers = sign_webhook(body)
    headers["webhook-timestamp"] = "yesterday"
    with pytest.raises(WebhookVerificationError) as excinfo:
        verify_webhook(payload=body, headers=headers, secret=WEBHOOK_SECRET)
    assert excinfo.value.reason == "malformed_header"


def test_a_signature_header_with_no_v1_part_raises_malformed_header() -> None:
    body = event_body()
    headers = sign_webhook(body)
    headers["webhook-signature"] = "v0,deadbeef"
    with pytest.raises(WebhookVerificationError) as excinfo:
        verify_webhook(payload=body, headers=headers, secret=WEBHOOK_SECRET)
    assert excinfo.value.reason == "malformed_header"


def test_secret_rotation_passes_when_any_signature_matches() -> None:
    body = event_body()
    old_secret = "whsec_" + base64.b64encode(b"o" * 24).decode()
    active = sign_webhook(body)["webhook-signature"]
    ts = sign_webhook(body)["webhook-timestamp"]

    # Rebuild both signatures over the same timestamp, as the signer does.
    def sign_with(secret: str) -> str:
        raw = secret[6:]
        key = base64.b64decode(raw + "=" * (-len(raw) % 4))
        signed = b"evt_1." + ts.encode() + b"." + body
        return "v1," + base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()

    headers = {
        "webhook-id": "evt_1",
        "webhook-timestamp": ts,
        "webhook-signature": f"{sign_with(WEBHOOK_SECRET)} {sign_with(old_secret)}",
    }
    assert verify_webhook(payload=body, headers=headers, secret=WEBHOOK_SECRET).id == "evt_1"
    assert verify_webhook(payload=body, headers=headers, secret=old_secret).id == "evt_1"
    assert active  # the single-signature helper still produces a usable value


def test_header_lookup_is_case_insensitive() -> None:
    body = event_body()
    signed = sign_webhook(body)
    headers = {key.upper(): value for key, value in signed.items()}
    assert verify_webhook(payload=body, headers=headers, secret=WEBHOOK_SECRET).id == "evt_1"


def test_a_base64url_grandfathered_secret_still_verifies() -> None:
    raw_bytes = bytes(range(24))
    urlsafe = "whsec_" + base64.urlsafe_b64encode(raw_bytes).decode().rstrip("=")
    body = event_body()
    ts = str(int(time.time()))
    signed = b"evt_1." + ts.encode() + b"." + body
    signature = base64.b64encode(hmac.new(raw_bytes, signed, hashlib.sha256).digest()).decode()
    headers = {
        "webhook-id": "evt_1",
        "webhook-timestamp": ts,
        "webhook-signature": "v1," + signature,
    }
    assert verify_webhook(payload=body, headers=headers, secret=urlsafe).id == "evt_1"


def test_the_now_argument_makes_verification_deterministic() -> None:
    body = event_body()
    headers = sign_webhook(body, timestamp=1_800_000_000)
    event = verify_webhook(payload=body, headers=headers, secret=WEBHOOK_SECRET, now=1_800_000_060)
    assert event.id == "evt_1"


def test_the_event_id_is_the_documented_dedup_key() -> None:
    body = event_body()
    headers = sign_webhook(body)
    event = verify_webhook(payload=body, headers=headers, secret=WEBHOOK_SECRET)
    assert event.id == headers["webhook-id"]
