#!/usr/bin/env bash
set -euo pipefail

WEB_CONTAINER="${MIMIRQ_WEB_CONTAINER:-mimirq-web-smoke-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}}"

port_mapping="$(docker port "$WEB_CONTAINER" 3000/tcp | head -n 1)"
if [[ -z "$port_mapping" ]]; then
  echo "[jwt-browser-smoke] web container has no published 3000/tcp port: $WEB_CONTAINER" >&2
  exit 1
fi
mapped_port="${port_mapping##*:}"
if [[ ! "$mapped_port" =~ ^[0-9]+$ ]]; then
  echo "[jwt-browser-smoke] invalid mapped port for $WEB_CONTAINER" >&2
  exit 1
fi
web_base_url="http://127.0.0.1:${mapped_port}"

if [[ -n "${MIMIRQ_SMOKE_IDENTIFIER:-}" || -n "${MIMIRQ_SMOKE_PASSWORD:-}" ]]; then
  if [[ -z "${MIMIRQ_SMOKE_IDENTIFIER:-}" || -z "${MIMIRQ_SMOKE_PASSWORD:-}" ]]; then
    echo "[jwt-browser-smoke] MIMIRQ_SMOKE_IDENTIFIER and MIMIRQ_SMOKE_PASSWORD must be set together" >&2
    exit 1
  fi
  jwt_identifier="$MIMIRQ_SMOKE_IDENTIFIER"
  jwt_email=""
  jwt_password="$MIMIRQ_SMOKE_PASSWORD"
  reuse_account=1
else
  read -r jwt_identifier jwt_email jwt_password < <(
    node - <<'JS'
const crypto = require('node:crypto')

const clean = (value, fallback) => String(value || fallback).replace(/[^a-zA-Z0-9-]/g, '-')
const runId = clean(process.env.GITHUB_RUN_ID, 'local')
const attempt = clean(process.env.GITHUB_RUN_ATTEMPT, '1')
const suffix = crypto.randomBytes(4).toString('hex')
const identifier = `ci-jwt-${runId}-${attempt}-${suffix}`.slice(0, 64)
const email = `${identifier}@example.com`
const password = `MimirQ-${crypto.randomBytes(24).toString('base64url')}`
process.stdout.write([identifier, email, password].join('\t') + '\n')
JS
  )
  reuse_account=0
fi

register_response="$(mktemp)"
register_payload="$(mktemp)"
cleanup() {
  rm -f "$register_response" "$register_payload"
}
trap cleanup EXIT
chmod 600 "$register_response" "$register_payload"

if [[ "$reuse_account" == "0" ]]; then
  JWT_EMAIL="$jwt_email" JWT_IDENTIFIER="$jwt_identifier" JWT_PASSWORD="$jwt_password" \
    node - <<'JS' >"$register_payload"
process.stdout.write(
  JSON.stringify({
    email: process.env.JWT_EMAIL,
    username: process.env.JWT_IDENTIFIER,
    password: process.env.JWT_PASSWORD,
  })
)
JS

  register_status="$(
    curl --noproxy '*' --silent --show-error \
      --output "$register_response" \
      --write-out '%{http_code}' \
      --header 'Content-Type: application/json' \
      --data-binary @"$register_payload" \
      "${web_base_url}/api/v1/auth/register"
  )"
  if [[ "$register_status" != "201" ]]; then
    echo "[jwt-browser-smoke] temporary account registration failed: http_status=$register_status" >&2
    exit 1
  fi
fi

if [[ -n "${GITHUB_ENV:-}" && "$reuse_account" == "0" ]]; then
  if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
    printf '::add-mask::%s\n' "$jwt_password"
  fi
  {
    printf 'PLAYWRIGHT_LIVE_IDENTIFIER=%s\n' "$jwt_identifier"
    printf 'PLAYWRIGHT_LIVE_PASSWORD=%s\n' "$jwt_password"
    printf 'MIMIRQ_SMOKE_IDENTIFIER=%s\n' "$jwt_identifier"
    printf 'MIMIRQ_SMOKE_PASSWORD=%s\n' "$jwt_password"
  } >>"$GITHUB_ENV"
fi

PLAYWRIGHT_EXTERNAL_SERVER=1 \
PLAYWRIGHT_LIVE_STACK=1 \
PLAYWRIGHT_PORT="$mapped_port" \
PLAYWRIGHT_LIVE_IDENTIFIER="$jwt_identifier" \
PLAYWRIGHT_LIVE_PASSWORD="$jwt_password" \
  pnpm --dir web exec playwright test e2e/live-stack.smoke.spec.ts
