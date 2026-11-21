import { parseBackendRoutes, parseFrontendRoutes } from './api-contract-lib.mjs'

function main() {
  const backend = parseBackendRoutes()
  const frontend = parseFrontendRoutes()

  const missing = []
  for (const route of frontend) {
    const key = `${route.method} ${route.path}`
    if (!backend.has(key)) {
      missing.push({ ...route, key })
    }
  }

  if (missing.length === 0) {
    console.log('[api-contract] OK: all web routes exist in backend')
    return
  }

  console.error('[api-contract] FAIL: missing backend routes for web calls:')
  for (const route of missing) {
    console.error(`- ${route.key}  (from ${route.src})`)
  }
  process.exitCode = 1
}

main()
