"""Standard Webhooks signature verification for inbound Postify deliveries.

Every delivery carries::

    webhook-id:        <stable event id — SAME across every retry and replay>
    webhook-timestamp: <unix seconds of THIS attempt>
    webhook-signature: v1,<base64 HMAC-SHA256>[ v1,<second signature>]

The signed content is ``{id}.{timestamp}.{raw_body}``, keyed with the
base64-decoded bytes of the secret after its ``whsec_`` prefix. Multiple
space-separated signatures mean a secret rotation is in flight — any one that
verifies is enough.

Two rules that are easy to get wrong and expensive to get wrong:

1. **Verify over the raw request bytes, before parsing JSON.** Re-serializing the
   body changes whitespace and key order, and the signature will never match.
2. **Delivery is at-least-once.** ``webhook-id`` equals the envelope's ``id`` and
   is stable across retries and replays — use it as your dedup key.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
from collections.abc import Mapping
from typing import Optional, Union

from .errors import WebhookVerificationError
from .models import WebhookEventEnvelope

__all__ = [
    "WEBHOOK_ID_HEADER",
    "WEBHOOK_SIGNATURE_HEADER",
    "WEBHOOK_TIMESTAMP_HEADER",
    "WEBHOOK_TOLERANCE_SEC",
    "verify_webhook",
]

WEBHOOK_ID_HEADER = "webhook-id"
WEBHOOK_TIMESTAMP_HEADER = "webhook-timestamp"
WEBHOOK_SIGNATURE_HEADER = "webhook-signature"

#: Maximum accepted clock skew in either direction, in seconds.
WEBHOOK_TOLERANCE_SEC = 300


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    value = headers.get(name)
    if value is not None:
        return value
    lowered = name.lower()
    for key, candidate in headers.items():
        if str(key).lower() == lowered:
            return candidate
    return None


def _secret_bytes(secret: str) -> bytes:
    """Decode a ``whsec_``-prefixed secret, accepting base64 and base64url alike.

    Pre-Phase-3 secrets were minted with the base64url alphabet, and the signer's
    (Node) decoder accepts both — so this one must too, or grandfathered
    endpoints would silently fail verification.
    """
    raw = secret[6:] if secret.startswith("whsec_") else secret
    normalized = raw.replace("-", "+").replace("_", "/")
    padding = "=" * (-len(normalized) % 4)
    try:
        return base64.b64decode(normalized + padding)
    except (binascii.Error, ValueError):
        # Not base64 at all: fall back to the literal bytes so a hand-made
        # secret still produces a deterministic (and consistent) key.
        return raw.encode("utf-8")


def _expected_signature(secret: str, webhook_id: str, timestamp: str, payload: bytes) -> str:
    signed = webhook_id.encode("utf-8") + b"." + timestamp.encode("utf-8") + b"." + payload
    digest = hmac.new(_secret_bytes(secret), signed, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_webhook(
    *,
    payload: Union[bytes, bytearray, str],
    headers: Mapping[str, str],
    secret: str,
    tolerance_sec: int = WEBHOOK_TOLERANCE_SEC,
    now: Optional[float] = None,
) -> WebhookEventEnvelope:
    """Verify a delivery's signature and return the parsed event envelope.

    Args:
        payload: The **raw** request body. Pass the bytes your framework received;
            never a re-serialized dict.
        headers: The request headers (case-insensitive lookup).
        secret: The endpoint's ``whsec_…`` signing secret.
        tolerance_sec: Accepted clock skew in either direction.
        now: Unix seconds, for testing.

    Raises:
        WebhookVerificationError: with ``.reason`` one of ``missing_headers``,
            ``malformed_header``, ``timestamp_out_of_tolerance`` or
            ``no_matching_signature``.

    Example::

        from postify import verify_webhook, WebhookVerificationError

        def handle(request):
            try:
                event = verify_webhook(
                    payload=request.get_data(),   # raw bytes
                    headers=request.headers,
                    secret=WEBHOOK_SECRET,
                )
            except WebhookVerificationError:
                return "", 400
            if already_processed(event.id):       # at-least-once delivery
                return "", 200
            process(event)
            return "", 200
    """
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)

    webhook_id = _header(headers, WEBHOOK_ID_HEADER)
    timestamp = _header(headers, WEBHOOK_TIMESTAMP_HEADER)
    signature_header = _header(headers, WEBHOOK_SIGNATURE_HEADER)
    if not webhook_id or not timestamp or not signature_header:
        raise WebhookVerificationError(
            "missing_headers",
            "Delivery is missing webhook-id, webhook-timestamp or webhook-signature.",
        )

    try:
        sent_at = int(str(timestamp).strip())
    except ValueError as exc:
        raise WebhookVerificationError(
            "malformed_header", "webhook-timestamp is not an integer."
        ) from exc

    current = time.time() if now is None else now
    if abs(current - sent_at) > tolerance_sec:
        raise WebhookVerificationError(
            "timestamp_out_of_tolerance",
            f"webhook-timestamp is outside the ±{tolerance_sec}s tolerance window.",
        )

    candidates = [
        part.split(",", 1)[1]
        for part in str(signature_header).split()
        if part.startswith("v1,") and len(part) > 3
    ]
    if not candidates:
        raise WebhookVerificationError(
            "malformed_header", "webhook-signature carried no v1 signature."
        )

    expected = _expected_signature(secret, str(webhook_id), str(timestamp).strip(), raw)
    if not any(hmac.compare_digest(expected, candidate) for candidate in candidates):
        raise WebhookVerificationError(
            "no_matching_signature", "No signature in webhook-signature matched."
        )

    return WebhookEventEnvelope.model_validate_json(raw)
