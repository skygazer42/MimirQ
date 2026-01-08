import { parseBackendRoutes, parseFrontendRoutes } from '../web/scripts/api-contract-lib.mjs'

const FRONTEND_CONTRACT_FILES = ['web/lib/api-client.ts']

function main() {
  const backend = parseBackendRoutes()
  const frontend = parseFrontendRoutes({ files: FRONTEND_CONTRACT_FILES })

  const frontendKeys = new Set(frontend.map((r) => `${r.method} ${r.path}`))

  const missing = []
  for (const [key, src] of backend.entries()) {
    if (!frontendKeys.has(key)) {
      missing.push({ key, src })
    }
  }

  if (missing.length === 0) {
    console.log('[api-coverage] OK: all backend routes are represented in web API client')
    return
  }

  console.error('[api-coverage] FAIL: backend routes missing in web API client:')
  for (const m of missing) {
    console.error(`- ${m.key}  (backend: ${m.src})`)
  }
  process.exitCode = 1
}

main()
