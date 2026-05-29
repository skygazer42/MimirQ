// Field-level API type drift detector.
//
// The existing `check-api-contract` / `check-api-coverage` scripts verify that
// frontend route paths exist in the backend. They do NOT detect when a frontend
// module hand-writes response/request *types* instead of consuming the generated
// OpenAPI types (web/types/openapi.ts via web/types/backend.ts aliases). Such
// hand-written types silently drift when the backend schema changes.
//
// This script scans web/lib/api/*.ts and reports modules that still declare
// hand-written object/interface types (the drift source), plus the apiClient vs
// openapiRequest call mix. It is a WARNING-level report by default (exit 0) so it
// can run in CI without blocking; pass --strict to fail when hand-written types
// exceed the allowed baseline.

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const API_DIR = path.resolve(__dirname, '..', 'lib', 'api')

// Modules intentionally exempt (infra, not API contract surfaces).
const EXEMPT = new Set(['core.ts', 'index.ts', 'openapi-request.ts', 'document-helpers.ts'])

// Baseline: number of modules still hand-writing types. Ratchet this DOWN over
// time as modules migrate to generated types. CI --strict fails if it grows.
const HANDWRITTEN_MODULE_BASELINE = 30

function listApiModules() {
  return fs
    .readdirSync(API_DIR)
    .filter((f) => f.endsWith('.ts') && !f.endsWith('.test.ts') && !EXEMPT.has(f))
    .sort()
}

function analyze(file) {
  const src = fs.readFileSync(path.join(API_DIR, file), 'utf8')
  // Hand-written object/interface types (drift source). Re-exports
  // (`export type { X }`) and alias types (`= OpenApiSchema<...>`) do NOT match.
  const handwrittenObject = [...src.matchAll(/export\s+type\s+(\w+)\s*=\s*\{/g)].map((m) => m[1])
  const handwrittenIface = [...src.matchAll(/export\s+interface\s+(\w+)\s*\{/g)].map((m) => m[1])
  const handwritten = [...handwrittenObject, ...handwrittenIface]
  const apiClientCalls = (src.match(/apiClient\.(get|post|put|patch|delete)\b/g) || []).length
  const openapiRequestCalls = (src.match(/openapiRequest\s*\(/g) || []).length
  return { file, handwritten, apiClientCalls, openapiRequestCalls }
}

function main() {
  const strict = process.argv.includes('--strict')
  const modules = listApiModules().map(analyze)

  const withHandwritten = modules.filter((m) => m.handwritten.length > 0)
  const totalHandwritten = modules.reduce((n, m) => n + m.handwritten.length, 0)

  console.log('[api-types-drift] frontend API type drift report')
  console.log(
    `[api-types-drift] modules=${modules.length} hand-written-type modules=${withHandwritten.length} hand-written types=${totalHandwritten}`
  )

  if (withHandwritten.length > 0) {
    console.log('[api-types-drift] modules still hand-writing types (consider migrating to @/types/backend aliases):')
    for (const m of withHandwritten) {
      console.log(
        `  - ${m.file}: ${m.handwritten.length} type(s) [${m.handwritten.join(', ')}] ` +
          `(apiClient=${m.apiClientCalls}, openapiRequest=${m.openapiRequestCalls})`
      )
    }
  } else {
    console.log('[api-types-drift] OK: no hand-written API types found')
  }

  if (strict && withHandwritten.length > HANDWRITTEN_MODULE_BASELINE) {
    console.error(
      `[api-types-drift] FAIL (--strict): ${withHandwritten.length} modules exceed baseline ${HANDWRITTEN_MODULE_BASELINE}`
    )
    process.exitCode = 1
    return
  }

  // Warning-level by default: always exit 0 so CI is not blocked yet.
  console.log('[api-types-drift] done (warning-level; pass --strict to enforce baseline)')
}

main()
