#!/usr/bin/env node
/**
 * Quick backend reachability check for local frontend dev.
 *
 * This is intentionally lightweight and does not require the backend to be in Docker;
 * it just pings the public base URL that the browser would call.
 */

function resolveBaseUrl() {
  const raw = String(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").trim()
  return raw.replace(/\/+$/, "")
}

async function fetchJson(url, { timeoutMs = 5000 } = {}) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    })
    const requestId = res.headers.get("x-request-id") || res.headers.get("X-Request-ID") || undefined
    let json = null
    try {
      json = await res.json()
    } catch {
      // ignore invalid json
    }
    return { ok: res.ok, status: res.status, requestId, json }
  } finally {
    clearTimeout(timeout)
  }
}

async function main() {
  const base = resolveBaseUrl()
  const endpoints = [
    { name: "health", url: `${base}/api/v1/health` },
    { name: "ready", url: `${base}/api/v1/health/ready` },
  ]

  console.log(`[api-ping] base=${base}`)

  let failed = 0
  for (const ep of endpoints) {
    try {
      const out = await fetchJson(ep.url)
      const rid = out.requestId ? ` request_id=${out.requestId}` : ""
      console.log(`[api-ping] ${ep.name} ${out.status}${rid}`)
      if (!out.ok) {
        failed++
        if (out.json) console.log(JSON.stringify(out.json, null, 2))
      }
    } catch (err) {
      failed++
      console.error(`[api-ping] ${ep.name} ERROR: ${String(err?.message || err)}`)
    }
  }

  if (failed) process.exit(1)
}

main()
