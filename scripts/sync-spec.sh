#!/usr/bin/env bash
# Refresh the vendored OpenAPI parity fixture at spec/v1.json.
#
# Source of truth is the live, UNAUTHENTICATED spec endpoint:
#   https://app.usepostify.com/v1/openapi.json
# The app repo's CI already guarantees that endpoint is byte-identical to its
# committed `apps/web/openapi/v1.json` artifact (determinism + oasdiff gates),
# so curling production is equivalent to reading the app repo — and it works
# from CI, which cannot see the app repo at all.
#
# Set POSTIFY_SPEC_SOURCE to a local path to vendor from a checkout instead:
#   POSTIFY_SPEC_SOURCE=../postify-new/apps/web/openapi/v1.json ./scripts/sync-spec.sh
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest="${repo_root}/spec/v1.json"
url="${POSTIFY_SPEC_URL:-https://app.usepostify.com/v1/openapi.json}"

if [[ -n "${POSTIFY_SPEC_SOURCE:-}" ]]; then
  echo "Vendoring spec from ${POSTIFY_SPEC_SOURCE}"
  cp "${POSTIFY_SPEC_SOURCE}" "${dest}"
else
  echo "Fetching spec from ${url}"
  curl -fsSL "${url}" -o "${dest}.tmp"
  python -c "import json,sys; json.load(open(sys.argv[1]))" "${dest}.tmp"
  mv "${dest}.tmp" "${dest}"
fi

ops=$(python - "$dest" <<'PY'
import json, sys

doc = json.load(open(sys.argv[1], encoding="utf-8"))
methods = {"get", "put", "post", "patch", "delete", "head", "options"}
print(sum(1 for ops in doc["paths"].values() for m in ops if m in methods))
PY
)
echo "spec/v1.json updated — ${ops} operations"
