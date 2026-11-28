import { listFrontendSourceFiles, parseBackendRoutes, parseFrontendRoutes } from './api-contract-lib.mjs'

const FRONTEND_CONTRACT_FILES = listFrontendSourceFiles().filter((rel) => rel.startsWith('web/lib/api/'))

// Service callbacks, offline workflows, and retired endpoints have no browser entrypoint.
const NON_BROWSER_BACKEND_ROUTES = new Set([
  'POST /auth/saml/bridge/consume',
  'POST /integrations/dify/conversation-turns',
  'POST /rag/image-index',
  'POST /rag/image-search-preview',
  // The precheck workspace opens files by finding instead of directory prefix.
  'GET /datasets/{}/precheck/scan-runs/{}/files',
  // The table workspace uses the query endpoint. The remote table probe uses preview.
  'GET /datasets/{}/tables/{}/preview',
  // The browser reads enriched feedback. Tooling reads raw feedback and exports training data.
  'GET /feedback/messages',
  'POST /feedback/loop/hard-negatives/export',
  // Deployment access reviews use the audit CLI.
  'GET /audit/access-graph/export',
  'GET /audit/access-graph/summary',
  // Published ontology business queries are programmatic integration entrypoints.
  // The authoring workbench uses its fixed-version question/document/action APIs.
  'POST /kg/ontologies/{}/versions/{}/metrics/{}',
  'POST /kg/ontologies/{}/versions/{}/objects/{}/lookup',
  'POST /kg/ontologies/{}/versions/{}/relations/{}/from/{}',
  'POST /kg/ontologies/{}/versions/{}/rules/{}',
  'POST /kg/ontologies/{}/versions/{}/functions/{}',
  'POST /kg/ontologies/datasets/{}/ask',
  'POST /kg/ontologies/ask',
])

function main() {
  const backend = parseBackendRoutes()
  const frontend = parseFrontendRoutes({ files: FRONTEND_CONTRACT_FILES })

  const frontendKeys = new Set(frontend.map((r) => `${r.method} ${r.path}`))

  const missing = []
  for (const [key, src] of backend.entries()) {
    if (NON_BROWSER_BACKEND_ROUTES.has(key)) continue
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
