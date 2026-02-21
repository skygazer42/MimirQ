#!/usr/bin/env node
/**
 * OpenAPI coverage guard.
 *
 * Goal: ensure `web/openapi.json` (exported from FastAPI) covers every backend v1 route
 * that the static API contract checker knows about.
 *
 * This is complementary to:
 * - api-contract: frontend calls -> backend routes
 * - api-coverage: backend routes -> web API client
 *
 * This guard prevents a different class of drift:
 * - backend route exists, but OpenAPI export doesn't include it
 *   (e.g. include_in_schema=false, missing router include, etc.)
 */

import { parseBackendRoutes, normalizeRoute, readText } from './api-contract-lib.mjs'

const HTTP_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])

function stripApiV1Prefix(rawPath) {
  const p = String(rawPath || '')
  if (p === '/api/v1') return '/'
  if (p.startsWith('/api/v1/')) return p.slice('/api/v1'.length)
  return p
}

function parseOpenapiRoutes() {
  const spec = JSON.parse(readText('web/openapi.json'))
  const paths = spec?.paths && typeof spec.paths === 'object' ? spec.paths : {}

  const out = new Set()

  for (const [rawPath, ops] of Object.entries(paths)) {
    const stripped = stripApiV1Prefix(rawPath)
    const normalized = normalizeRoute(stripped)
    if (!ops || typeof ops !== 'object') continue

    for (const method of Object.keys(ops)) {
      if (String(method || '').startsWith('x-')) continue
      const upper = String(method || '').toUpperCase()
      if (!HTTP_METHODS.has(upper)) continue
      out.add(`${upper} ${normalized}`)
    }
  }

  return out
}

function main() {
  const backend = parseBackendRoutes()
  const openapi = parseOpenapiRoutes()

  const missing = []
  for (const [key, src] of backend.entries()) {
    if (!openapi.has(key)) missing.push({ key, src })
  }

  // OpenAPI will include non-v1 routes (e.g. /metrics, /). We don't fail on extras,
  // but we do print the first few to help diagnose parser gaps.
  const extras = []
  for (const key of openapi.values()) {
    if (!backend.has(key)) extras.push(key)
  }
  extras.sort()

  if (!missing.length) {
    process.stdout.write(
      `[openapi-coverage] OK: ${backend.size} backend routes covered (${openapi.size} OpenAPI routes; extras: ${extras.length})\n`
    )
    return
  }

  missing.sort((a, b) => a.key.localeCompare(b.key))
  process.stderr.write(
    `[openapi-coverage] FAIL: missing ${missing.length} backend routes in web/openapi.json\n\n`
  )
  for (const m of missing.slice(0, 200)) {
    process.stderr.write(`- ${m.key}  (backend: ${m.src})\n`)
  }
  if (missing.length > 200) {
    process.stderr.write(`\n...and ${missing.length - 200} more\n`)
  }

  process.stderr.write('\nHint: Run `make openapi-export` and ensure the routes are included in schema.\n')
  process.exit(1)
}

main()

