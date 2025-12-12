# To run (in Bash): git update-index --add --chmod=+x scripts/smoke_api.sh
#!/usr/bin/env bash
set -euo pipefail

API_URL="${HDT_API_BASE:-http://localhost:5000}"
API_URL="${API_URL%/}"

API_KEY="${MODEL_DEVELOPER_1_API_KEY:-MODEL_DEVELOPER_1}"

# Canonical header only: Authorization: Bearer
hdr=(-H "Authorization: Bearer ${API_KEY}" -sS)

echo "→ GET ${API_URL}/healthz"
curl "${hdr[@]}" "${API_URL}/healthz" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'
echo "✔ healthz ok"

USER_ID="${SMOKE_USER_ID:-3}"

echo "→ GET ${API_URL}/get_walk_data?user_id=${USER_ID}"
json="$(curl "${hdr[@]}" "${API_URL}/get_walk_data?user_id=${USER_ID}")"
if grep -q "\"user_id\"[[:space:]]*:[[:space:]]*${USER_ID}" <<<"$json"; then
  echo "✔ get_walk_data ok for user ${USER_ID}"
else
  echo "✖ did not find expected user_id ${USER_ID} in response"
  echo "$json"
  exit 1
fi
