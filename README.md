# postify

Official Python SDK for the [Postify](https://usepostify.com) API — schedule and publish
social posts, manage media, read analytics, and consume webhooks from Python.

- Sync **and** async clients, both context managers
- Fully typed, ships `py.typed`
- RFC 9457 problems mapped to a typed exception hierarchy you can branch on
- Auto-paginating keyset cursors that carry your filters forward
- Idempotency keys generated for you, and mutations that are **never** silently retried
- Rate-limit headers parsed — and never invented
- Standard Webhooks signature verification
- Runtime dependencies: `httpx` and `pydantic`. That's it.

```bash
pip install postify
```

Requires Python 3.9+.

## 60-second quickstart

```python
import os

from postify import Postify

with Postify(api_key=os.environ["POSTIFY_API_KEY"]) as client:
    # Which accounts can we publish to?
    channels = client.channels.list()
    live = [c for c in channels if c.status == "live"]
    print(f"{len(live)} live channels")

    # Schedule a post to the first live channel.
    post = client.posts.create(
        variants=[{"channel_id": live[0].id, "body": "Shipping the new API today."}],
        scheduled_at="2026-09-01T15:00:00Z",
    )
    print(post.id, post.status)

    # Walk everything that's queued up.
    for scheduled in client.posts.list(status="scheduled"):
        print(scheduled.id, scheduled.scheduled_at)
```

## Authentication

Mint an organization API key in **Postify → Settings → API keys**. Keys look like
`postify_live_…`. The client reads `$POSTIFY_API_KEY` when you don't pass one.

```python
from postify import Postify

# Default: Authorization: Bearer postify_live_…
client = Postify(api_key="postify_live_examplekey1234")

# Alternate scheme the API also accepts: x-api-key: postify_live_…
header_client = Postify(api_key="postify_live_examplekey1234", auth_style="header")

# Keys are never printed in full — repr and logs are redacted.
print(repr(client))
client.close()
header_client.close()
```

Full constructor:

```python
import httpx

from postify import Postify

client = Postify(
    api_key="postify_live_examplekey1234",
    base_url="https://app.usepostify.com",  # DEFAULT_BASE_URL
    timeout=60.0,  # DEFAULT_TIMEOUT, per attempt
    max_retries=2,  # DEFAULT_MAX_RETRIES
    auth_style="bearer",  # "bearer" | "header"
    default_headers={"X-App": "my-service"},
    http_client=httpx.Client(),  # bring your own pool/proxies
)
client.close()
```

Scopes map to resources: `channels:read`, `posts:read`, `posts:write`,
`analytics:read`, `webhooks:read`, `webhooks:write`. Two things that surprise people:
**media rides the `posts:*` scopes** (there is no `media:*` scope), and **usage rides
`analytics:read`** (there is no `usage:read`).

## Errors

Every non-2xx response is an RFC 9457 problem document. Branch on `err.code` — never on
`title` or `detail`, and always keep a fallback branch, because codes are append-only and
a future one must not crash your integration.

| Status | Exception | Codes |
|---|---|---|
| 400 | `BadRequestError` | `invalid_request`, `validation_failed` |
| 401 | `AuthenticationError` | `authentication_required`, `invalid_api_key` |
| 403 | `PermissionDeniedError` | `insufficient_scope`, `feature_not_enabled`, `dangerous_ops_disabled` |
| 404 | `NotFoundError` | `resource_not_found` |
| 409 | `ConflictError` | `resource_conflict`, `idempotency_in_progress` |
| 422 | `UnprocessableEntityError` | `idempotency_key_reused` |
| 429 | `RateLimitError` | `rate_limited`, `quota_exhausted` |
| ≥500 | `InternalServerError` | `internal_error` |
| other | `APIError` | — |

Transport failures raise `APIConnectionError` (or its subclass `APITimeoutError`), and a
cancelled call raises `APIUserAbortError`. All of them derive from `PostifyError`.

The 429 pair is the case that matters most: `rate_limited` is a burst window you should
wait out, `quota_exhausted` is your plan's period allowance and will not clear until the
billing period resets.

```python
from postify import Postify, RateLimitError, APIError

client = Postify(api_key="postify_live_examplekey1234")
try:
    client.posts.get("post_missing")
except RateLimitError as err:
    if err.code == "quota_exhausted":
        print("Plan quota is gone until the period resets — do not retry.")
    else:
        print("Burst limit; retry after", err.retry_after_seconds)
except APIError as err:
    print(err.status, err.code, err.request_id)
    for field in err.field_errors:  # populated on validation_failed
        print(field.pointer, field.message)
client.close()
```

## Pagination

`posts.list()` and `media.list()` are keyset-paginated; `channels.list()` and
`webhook_endpoints.list()` are plan-bounded and return plain lists.

```python
from postify import Postify

client = Postify(api_key="postify_live_examplekey1234")

# Auto-paginate items — filters are carried forward on every page.
for post in client.posts.list(status="scheduled", limit=100):
    print(post.id)

# Or walk page by page.
page = client.posts.list(limit=100).first_page()
while page is not None:
    print(len(page.data), page.has_more, page.next_cursor)
    page = page.get_next_page()

# Or just collect everything.
all_posts = list(client.posts.list())
print(len(all_posts))
client.close()
```

Cursors embed a fingerprint of the query they were minted with, so replaying one against
different filters is rejected server-side. The pager only ever swaps `after` — it never
lets a cursor and a changed filter set mix.

## Idempotency

`posts.create` is the one idempotent operation. The SDK generates an `Idempotency-Key`
(a UUID4) for every create, which is what makes retrying one safe. Same key + same body
within 24 h replays the original response; same key + a *different* body is a 422
`idempotency_key_reused`; a still-in-flight original is a 409 `idempotency_in_progress`.

```python
from postify import Postify

client = Postify(api_key="postify_live_examplekey1234")

# Auto-generated key (default).
post = client.posts.create(variants=[{"channel_id": "chn_1", "body": "hi"}], draft=True)

# Your own key — safe to re-issue after a crash.
again = client.posts.create(
    variants=[{"channel_id": "chn_1", "body": "hi"}],
    draft=True,
    idempotency_key="order-42-post",
)
print(again.id, again.idempotency_replayed)

# Opt out entirely (this also makes the request non-retryable).
unkeyed = client.posts.create(
    variants=[{"channel_id": "chn_1", "body": "hi"}],
    draft=True,
    idempotency_key=False,
)
print(post.id, unkeyed.id)
client.close()
```

## Retries and rate limits

Default `max_retries=2` (three attempts). The policy:

| Condition | Retry? | Delay |
|---|---|---|
| Connection/timeout error on a GET or a **keyed** mutation | yes | full-jitter backoff, base 0.5 s, cap 8 s |
| Anything at all on an **unkeyed mutation** | **no** | — |
| 429 `rate_limited` | yes | `Retry-After`, else draft-11 `t`, else backoff |
| 429 `quota_exhausted` | no | — |
| 408, and 409 `idempotency_in_progress` | yes | `Retry-After` |
| 500 / 502 / 503 / 504 | yes | backoff |
| every other 4xx | no | — |

The unkeyed-mutation rule is deliberate: `posts.delete`, `posts.reschedule` and
`posts.publish` are not idempotent server-side, so a connection failure surfaces to you
rather than risking a double publish. `posts.create` is always keyed, so it is always
safe to retry. A `Retry-After` longer than 60 s is not slept through — the error surfaces
so you can schedule the work properly.

Rate-limit headers (both the IETF draft-11 structured fields and the legacy `X-` trio)
are parsed onto the client and onto errors. Absent values stay `None` — the SDK never
guesses that `remaining == limit`.

```python
from postify import Postify

client = Postify(api_key="postify_live_examplekey1234")
client.usage.get()

state = client.last_rate_limit
if state is not None:
    print(state.policy, state.limit, state.remaining, state.reset_at)
print("request id:", client.last_request_id)
client.close()
```

## Media uploads

Uploading is create-ticket → presigned PUT → complete. `media.upload()` does all three,
and issues the PUT with **no Postify credential** (signing a presigned S3 URL with an API
key breaks the signature).

```python
from postify import Postify

client = Postify(api_key="postify_live_examplekey1234")

asset = client.media.upload(b"\x89PNG\r\n\x1a\n", filename="teaser.png")
print(asset.id, asset.status, asset.url)

client.posts.create(
    variants=[
        {
            "channel_id": "chn_1",
            "body": "Sneak peek",
            "media": [{"url": asset.url, "type": "image"}],
        }
    ],
    draft=True,
)
client.close()
```

## Webhooks

Postify signs deliveries Standard-Webhooks style. Verify over the **raw request bytes**,
before parsing JSON.

```python
from postify import verify_webhook, WebhookVerificationError

WEBHOOK_SECRET = "whsec_examplesecretvaluegoeshere=="
seen_event_ids = set()


def handle_delivery(raw_body: bytes, headers: dict) -> int:
    try:
        event = verify_webhook(payload=raw_body, headers=headers, secret=WEBHOOK_SECRET)
    except WebhookVerificationError as err:
        print("rejected:", err.reason)
        return 400

    # Delivery is at-least-once: webhook-id == event.id and is stable across
    # every retry and replay, so it is your dedup key.
    if event.id in seen_event_ids:
        return 200
    seen_event_ids.add(event.id)

    if event.type == "post.published":
        print("published", event.data.get("postId"))
    return 200


print(handle_delivery.__name__)
```

`WebhookVerificationError.reason` is one of `missing_headers`, `malformed_header`,
`timestamp_out_of_tolerance` (±`WEBHOOK_TOLERANCE_SEC`, 300 s) or `no_matching_signature`.
Space-separated signatures during a secret rotation are handled — any one that verifies
passes.

Managing endpoints:

```python
from postify import Postify

client = Postify(api_key="postify_live_examplekey1234")

endpoint = client.webhook_endpoints.create(
    url="https://api.example.com/postify/webhooks",
    event_types=["post.published", "post.failed"],
)
print(endpoint.signing_secret)  # shown ONCE — store it now

client.webhook_endpoints.test(endpoint.id)
client.webhook_endpoints.update(endpoint.id, enabled=False)
client.webhook_endpoints.delete(endpoint.id)
client.close()
```

An endpoint auto-disables after 20 consecutive failed deliveries; re-enable it with
`update(id, enabled=True)`, which also clears the failure counter.

## Async

Every method has an async twin with identical arguments and return types.

```python
import asyncio

from postify import AsyncPostify


async def main():
    async with AsyncPostify(api_key="postify_live_examplekey1234") as client:
        usage = await client.usage.get()
        print(usage.plan)

        async for post in client.posts.list(status="scheduled"):
            print(post.id)

        page = await client.media.list(limit=50).first_page()
        print(len(page.data))


asyncio.run(main())
```

## API reference

All 17 `/v1` operations, and the SDK method for each:

| Method | Path | SDK |
|---|---|---|
| GET | `/v1/channels` | `client.channels.list()` |
| GET | `/v1/posts` | `client.posts.list(...)` |
| POST | `/v1/posts` | `client.posts.create(...)` |
| GET | `/v1/posts/{id}` | `client.posts.get(id)` |
| PATCH | `/v1/posts/{id}` | `client.posts.reschedule(id, scheduled_at=...)` |
| DELETE | `/v1/posts/{id}` | `client.posts.delete(id)` |
| POST | `/v1/posts/{id}/publish` | `client.posts.publish(id)` |
| GET | `/v1/media` | `client.media.list(...)` |
| POST | `/v1/media/uploads` | `client.media.create_upload(...)` |
| POST | `/v1/media/uploads/{id}/complete` | `client.media.complete_upload(id)` |
| GET | `/v1/analytics` | `client.analytics.get()` |
| GET | `/v1/usage` | `client.usage.get()` |
| GET | `/v1/webhook-endpoints` | `client.webhook_endpoints.list()` |
| POST | `/v1/webhook-endpoints` | `client.webhook_endpoints.create(...)` |
| PATCH | `/v1/webhook-endpoints/{id}` | `client.webhook_endpoints.update(id, ...)` |
| DELETE | `/v1/webhook-endpoints/{id}` | `client.webhook_endpoints.delete(id)` |
| POST | `/v1/webhook-endpoints/{id}/test` | `client.webhook_endpoints.test(id)` |

Plus `client.media.upload(file)`, a Python-only convenience that chains the three upload
steps.

Full HTTP reference: <https://app.usepostify.com/docs/api-reference>.

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
ty check
pytest tests/unit --cov=postify --cov-fail-under=85
./scripts/sync-spec.sh          # refresh the vendored OpenAPI parity fixture
pytest tests/smoke              # hits production; skips loudly without POSTIFY_API_KEY
```

`tests/unit/test_openapi_parity.py` diffs `src/postify/_registry.py` against
`spec/v1.json` in both directions — a new server operation fails CI here until the SDK
implements it.

## License

MIT © Devino Solutions Inc.
