import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
// This script lives under backend/scripts. Repo root is two levels up.
const ROOT = path.resolve(__dirname, '..', '..')

function readText(relPath) {
  return fs.readFileSync(path.join(ROOT, relPath), 'utf8')
}

function normalizeRoute(routePath) {
  let p = String(routePath || '').trim()
  if (!p) return ''
  // Strip base URL if someone accidentally passed it.
  p = p.replace(/^https?:\/\/[^/]+/i, '')
  // Drop querystring for matching purposes.
  p = p.split('?')[0]
  // Normalize frontend template vars.
  p = p.replace(/\$\{[^}]+\}/g, '{}')
  // Normalize backend path params.
  p = p.replace(/\{[^}]+\}/g, '{}')
  if (!p.startsWith('/')) p = `/${p}`
  // Normalize trailing slash (except root).
  if (p.length > 1 && p.endsWith('/')) p = p.slice(0, -1)
  return p
}

function parseBackendPrefixes() {
  const initPy = readText('backend/app/api/v1/__init__.py')
  const map = new Map()

  // Matches: router.include_router(documents.router, prefix="/documents", ...)
  const re = /include_router\(\s*([A-Za-z_][A-Za-z0-9_]*)\.router\b([\s\S]*?)\)/g
  let m
  while ((m = re.exec(initPy))) {
    const mod = m[1]
    const args = m[2] || ''
    const prefixMatch = args.match(/prefix\s*=\s*(?:\"([^\"]*)\"|'([^']*)')/)
    const prefix = prefixMatch ? (prefixMatch[1] || prefixMatch[2] || '') : ''
    map.set(mod, prefix)
  }
  return map
}

function parseBackendRoutes() {
  const prefixes = parseBackendPrefixes()
  const routes = new Map() // key: METHOD PATH -> source

  const backendModules = []
  for (const [mod, prefix] of prefixes.entries()) {
    if (mod === 'kg') {
      backendModules.push({ mod, prefix, rel: 'backend/app/rag/kg/api/routes.py' })
    } else {
      backendModules.push({ mod, prefix, rel: `backend/app/api/v1/${mod}.py` })
    }
  }

  const routeRe = /@router\.(get|post|put|patch|delete)\(\s*(?:\"([^\"]*)\"|'([^']*)')/g

  for (const mod of backendModules) {
    const abs = path.join(ROOT, mod.rel)
    if (!fs.existsSync(abs)) continue
    const text = fs.readFileSync(abs, 'utf8')
    let m
    while ((m = routeRe.exec(text))) {
      const method = String(m[1] || '').toUpperCase()
      const rawPath = m[2] ?? m[3] ?? ''
      const prefix = mod.prefix || ''

      let full = ''
      if (!rawPath) {
        full = prefix || ''
      } else if (!prefix) {
        full = rawPath
      } else if (rawPath.startsWith('/')) {
        full = `${prefix}${rawPath}`
      } else {
        full = `${prefix}/${rawPath}`
      }

      const normalized = normalizeRoute(full)
      const key = `${method} ${normalized}`
      routes.set(key, mod.rel)
    }
  }

  return routes
}

function extractFrontendRoutesFromFile(rel) {
  const abs = path.join(ROOT, rel)
  const text = fs.readFileSync(abs, 'utf8')
  const out = []

  // axios client calls
  const axiosRe = /apiClient\.(get|post|put|patch|delete)\(\s*(?:`([^`]+)`|\"([^\"]+)\"|'([^']+)')/g
  let m
  while ((m = axiosRe.exec(text))) {
    const method = String(m[1] || '').toUpperCase()
    const rawPath = m[2] ?? m[3] ?? m[4] ?? ''
    out.push({ method, path: normalizeRoute(rawPath), src: rel })
  }

  // fetch(`${API_V1_BASE_URL}/...`, { method: 'GET' })
  const fetchRe =
    /fetch\(\s*`?\$\{API_V1_BASE_URL\}([^`"']+)`?\s*,\s*\{[\s\S]*?method\s*:\s*'([^']+)'/g
  while ((m = fetchRe.exec(text))) {
    const rawPath = m[1] || ''
    const method = String(m[2] || 'GET').toUpperCase()
    out.push({ method, path: normalizeRoute(rawPath), src: rel })
  }

  // fetch(`${API_V1_BASE_URL}/...`) with default method GET
  const fetchNoOptsRe = /fetch\(\s*`?\$\{API_V1_BASE_URL\}([^`"']+)`?\s*\)/g
  while ((m = fetchNoOptsRe.exec(text))) {
    const rawPath = m[1] || ''
    out.push({ method: 'GET', path: normalizeRoute(rawPath), src: rel })
  }

  return out
}

function listFrontendSourceFiles() {
  const frontendRoot = path.join(ROOT, 'frontend')
  if (!fs.existsSync(frontendRoot)) return []

  const IGNORE_DIRS = new Set([
    'node_modules',
    '.next',
    '.next_build',
    'out',
    'dist',
    'coverage',
  ])

  const exts = new Set(['.ts', '.tsx'])
  const files = []

  function walk(dirAbs) {
    const entries = fs.readdirSync(dirAbs, { withFileTypes: true })
    for (const ent of entries) {
      const abs = path.join(dirAbs, ent.name)
      if (ent.isDirectory()) {
        if (IGNORE_DIRS.has(ent.name)) continue
        walk(abs)
        continue
      }
      if (!ent.isFile()) continue
      const ext = path.extname(ent.name)
      if (!exts.has(ext)) continue
      const rel = path.relative(ROOT, abs)
      files.push(rel)
    }
  }

  walk(frontendRoot)
  return files
}

function parseFrontendRoutes() {
  const files = listFrontendSourceFiles()
  const routes = []
  for (const rel of files) {
    try {
      routes.push(...extractFrontendRoutesFromFile(rel))
    } catch {
      // ignore unreadable files
    }
  }

  // Dedup
  const uniq = new Map()
  for (const r of routes) {
    const key = `${r.method} ${r.path}`
    if (!uniq.has(key)) uniq.set(key, r)
  }
  return Array.from(uniq.values())
}

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
    console.log('[api-contract] OK: all frontend routes exist in backend')
    return
  }

  console.error('[api-contract] FAIL: missing backend routes for frontend calls:')
  for (const m of missing) {
    console.error(`- ${m.key}  (from ${m.src})`)
  }
  process.exitCode = 1
}

main()


