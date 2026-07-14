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

function listApiModules() {
  return fs
    .readdirSync(API_DIR)
    .filter((f) => f.endsWith('.ts') && !f.endsWith('.test.ts') && !EXEMPT.has(f))
    .sort()
}

function argumentValue(name) {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : undefined
}

function loadBaseline() {
  const baselineArg = argumentValue('--baseline')
  if (!baselineArg) {
    throw new Error('--baseline <file> is required with --strict')
  }
  const baselinePath = path.resolve(process.cwd(), baselineArg)
  const parsed = JSON.parse(fs.readFileSync(baselinePath, 'utf8'))
  const handwrittenModules = Number(parsed.handwrittenModules)
  const handwrittenTypes = Number(parsed.handwrittenTypes)
  if (!Number.isInteger(handwrittenModules) || handwrittenModules < 0) {
    throw new Error('baseline handwrittenModules must be a non-negative integer')
  }
  if (!Number.isInteger(handwrittenTypes) || handwrittenTypes < 0) {
    throw new Error('baseline handwrittenTypes must be a non-negative integer')
  }
  return { handwrittenModules, handwrittenTypes, baselinePath }
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

  if (strict) {
    let baseline
    try {
      baseline = loadBaseline()
    } catch (error) {
      console.error(`[api-types-drift] FAIL (--strict): ${error instanceof Error ? error.message : String(error)}`)
      process.exitCode = 1
      return
    }

    const failures = []
    if (withHandwritten.length > baseline.handwrittenModules) {
      failures.push(
        `hand-written-type modules=${withHandwritten.length} exceed baseline ${baseline.handwrittenModules}`
      )
    }
    if (totalHandwritten > baseline.handwrittenTypes) {
      failures.push(`hand-written types=${totalHandwritten} exceed baseline ${baseline.handwrittenTypes}`)
    }
    if (failures.length > 0) {
      for (const failure of failures) console.error(`[api-types-drift] FAIL (--strict): ${failure}`)
      process.exitCode = 1
      return
    }
    if (
      withHandwritten.length < baseline.handwrittenModules ||
      totalHandwritten < baseline.handwrittenTypes
    ) {
      console.log(
        `[api-types-drift] baseline can be lowered to modules=${withHandwritten.length}, types=${totalHandwritten}`
      )
    }
    console.log(`[api-types-drift] strict baseline passed (${baseline.baselinePath})`)
    return
  }

  console.log('[api-types-drift] done (warning-level; pass --strict to enforce baseline)')
}

main()
