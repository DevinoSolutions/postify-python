# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-05

Initial release. Full coverage of the Postify `/v1` public API — all 17
authenticated operations, sync and async.

### Added

- `Postify` and `AsyncPostify` clients, both context managers, with configurable
  `base_url`, `timeout`, `max_retries`, `auth_style` and an injectable
  `httpx.Client` / `httpx.AsyncClient`.
- Bearer (default) and `x-api-key` authentication; the key is read from
  `$POSTIFY_API_KEY` when not passed, and is redacted in every `repr` and log line.
- Resources: `channels`, `posts`, `media`, `analytics`, `usage` and
  `webhook_endpoints`.
- RFC 9457 problem documents mapped to a typed exception hierarchy
  (`BadRequestError`, `AuthenticationError`, `PermissionDeniedError`,
  `NotFoundError`, `ConflictError`, `UnprocessableEntityError`, `RateLimitError`,
  `InternalServerError`, plus `APIConnectionError` / `APITimeoutError` /
  `APIUserAbortError`), with the full `PROBLEM_CODES` registry exported.
- Auto-paginating keyset cursors for `posts.list` and `media.list` that carry the
  caller's filters forward verbatim (`SyncPager` / `AsyncPager`, `Page` /
  `AsyncPage`).
- Automatic `Idempotency-Key` generation on `posts.create`, with explicit-key and
  `idempotency_key=False` opt-out, and `Idempotency-Replayed` surfaced on the
  returned model.
- Retry policy honoring `Retry-After` (delta-seconds and HTTP-date), draft-11
  rate-limit hints and full-jitter backoff — and **never** retrying a mutation
  that carries no idempotency key.
- `RateLimitState` parsed from both the IETF draft-11 structured fields and the
  legacy `X-RateLimit-*` trio, exposed on `client.last_rate_limit`, on models and
  on `APIError.rate_limit`. Unobservable values stay `None`.
- `media.upload()` convenience that chains create-ticket → presigned PUT →
  complete, issuing the PUT with no Postify credential.
- `verify_webhook()` for Standard Webhooks deliveries, with raw-bytes
  verification, secret-rotation support and typed `.reason` failures.
- `py.typed` marker; the package ships full type information.

[Unreleased]: https://github.com/DevinoSolutions/postify-python/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/DevinoSolutions/postify-python/releases/tag/v0.1.0
