#!/usr/bin/env bash
# Builds the image, starts it with Docker Compose, drops one email into the inbox, and checks
# that a ready job with the right values appears. Cleans up after itself.
set -euo pipefail
cd "$(dirname "$0")/.."
export SMPLDOC_ADMIN_TOKEN="smoke-test-password"
export SMPLDOC_POLL_SECONDS=1
project="smpldoc-smoke-$$"
compose() { docker compose -p "$project" "$@"; }
trap 'compose logs --no-color 2>/dev/null | tail -40 || true; compose down -v >/dev/null 2>&1 || true' EXIT

compose up -d --build --wait --wait-timeout 120
auth="admin:${SMPLDOC_ADMIN_TOKEN}"

# The portal must refuse an unauthenticated request.
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3787/api/jobs)
[ "$code" = "401" ] || { echo "expected 401 without a password, got $code"; exit 1; }

# Drop an email into the inbox the way a mail source would.
printf 'From: a@example.test\r\nSubject: Smoke invoice\r\nMessage-ID: <smoke-1@example.test>\r\nContent-Type: text/plain\r\n\r\ninvoice_number: 1042\r\ntotal: 99.50\r\n' |
  compose exec -T smpldoc sh -c 'mkdir -p /data/blob/inbox && cat > /data/blob/inbox/smoke-1'

for _ in $(seq 1 30); do
  body=$(curl -s -u "$auth" http://127.0.0.1:3787/api/jobs)
  case "$body" in *'"status":"ready"'*) break ;; esac
  sleep 1
done
echo "$body" | grep -q '"status":"ready"' || { echo "no ready job: $body"; exit 1; }
id=$(echo "$body" | sed -E 's/.*"id":"([^"]+)".*/\1/')
curl -s -u "$auth" "http://127.0.0.1:3787/api/jobs/$id" | grep -q '"value":"1042"' || { echo "value not extracted"; exit 1; }
echo "smoke test passed"
