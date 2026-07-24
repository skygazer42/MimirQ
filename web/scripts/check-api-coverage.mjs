import { listFrontendSourceFiles, parseBackendRoutes, parseFrontendRoutes } from './api-contract-lib.mjs'

const FRONTEND_CONTRACT_FILES = listFrontendSourceFiles().filter(
  (rel) => rel === 'web/lib/api-client.ts' || rel.startsWith('web/lib/api/')
)

// Service-to-service callbacks are intentionally not callable by the browser API layer.
const SERVICE_ONLY_BACKEND_ROUTES = new Set([
  'POST /auth/saml/bridge/consume',
  'POST /integrations/dify/conversation-turns',
])

function main() {
  const backend = parseBackendRoutes()
  const frontend = parseFrontendRoutes({ files: FRONTEND_CONTRACT_FILES })

  const frontendKeys = new Set(frontend.map((r) => `${r.method} ${r.path}`))

  const missing = []
  for (const [key, src] of backend.entries()) {
    if (SERVICE_ONLY_BACKEND_ROUTES.has(key)) continue
    if (!frontendKeys.has(key)) {
      missing.push({ key, src })
    }
  }

  if (missing.length === 0) {
    console.log('[api-coverage] OK: all backend routes are represented in the web API layer')
    return
  }

  console.error('[api-coverage] FAIL: backend routes missing in the web API layer:')
  for (const m of missing) {
    console.error(`- ${m.key}  (backend: ${m.src})`)
  }
  process.exitCode = 1
}

main()
