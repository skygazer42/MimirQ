import { parseBackendRoutes, parseFrontendRoutes } from './api-contract-lib.mjs'

function main() {
  const backend = parseBackendRoutes()
  const frontend = parseFrontendRoutes()

  const missing = []
  for (const r of frontend) {
    const key = `${r.method} ${r.path}`
    if (!backend.has(key)) {
      missing.push({ ...r, key })
    }
  }

  if (missing.length === 0) {
    console.log('[api-contract] OK: all web routes exist in backend')
    return
  }

  console.error('[api-contract] FAIL: missing backend routes for web calls:')
  for (const m of missing) {
    console.error(`- ${m.key}  (from ${m.src})`)
  }
  process.exitCode = 1
}

main()
