#!/usr/bin/env node
/**
 * Quick backend reachability check for local frontend dev.
 *
 * This is intentionally lightweight and does not require the backend to be in Docker;
 * it just pings the public base URL that the browser would call.
 */

function resolveBaseUrl() {
  const configuredUrl = process.env.NEXT_PUBLIC_API_URL?.trim()
  const baseUrl = configuredUrl === undefined || configuredUrl === '' ? 'http://localhost:8000' : configuredUrl
  return baseUrl.replace(/\/+$/, '')
}

async function fetchJson(url) {
  const response = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(5_000),
  })
  const requestId = response.headers.get('x-request-id')
  const contentType = response.headers.get('content-type')
  const isJsonContentType = contentType !== null && /application\/json|application\/[^;]+\+json/i.test(contentType)

  const bodyText = await response.text()
  let json = null
  let jsonError = null
  if (bodyText !== '') {
    try {
      json = JSON.parse(bodyText)
    } catch (error) {
      jsonError = error instanceof Error ? error.message : String(error)
    }
  }

  const ok = response.ok && isJsonContentType && json !== null && typeof json === 'object'
  const snippet = bodyText.trimStart().slice(0, 160)
  return { ok, status: response.status, requestId, json, jsonError, contentType, snippet }
}

async function main() {
  const base = resolveBaseUrl()
  const endpoints = [
    { name: 'health', url: `${base}/api/v1/health` },
    { name: 'ready', url: `${base}/api/v1/health/ready` },
    { name: 'meta', url: `${base}/api/v1/meta` },
  ]

  console.log(`[api-ping] base=${base}`)

  let failed = false
  for (const ep of endpoints) {
    try {
      const out = await fetchJson(ep.url)
      const rid = out.requestId ? ` request_id=${out.requestId}` : ''
      console.log(`[api-ping] ${ep.name} ${out.status}${rid}`)
      if (!out.ok) {
        failed = true
        const ct = out.contentType ? ` content-type=${out.contentType}` : ''
        console.error(`[api-ping] ${ep.name} FAIL${ct}`)
        if (out.json !== null) console.error(JSON.stringify(out.json, null, 2))
        else if (out.jsonError) console.error(`[api-ping] ${ep.name} JSON parse error: ${out.jsonError}`)
        if (out.snippet) console.error(`[api-ping] ${ep.name} body: ${out.snippet}`)
      }
    } catch (error) {
      failed = true
      const message = error instanceof Error ? error.message : String(error)
      console.error(`[api-ping] ${ep.name} ERROR: ${message}`)
    }
  }

  if (failed) process.exitCode = 1
}

main()
