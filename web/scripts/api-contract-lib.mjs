import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
// This script lives under web/scripts/. Repo root is two levels up.
const ROOT = path.resolve(__dirname, '../..')

export function readText(relPath) {
  return fs.readFileSync(path.join(ROOT, relPath), 'utf8')
}

export function normalizeRoute(routePath) {
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

function stripApiV1Prefix(normalizedPath) {
  const p = String(normalizedPath || '')
  if (p === '/api/v1') return '/'
  if (p.startsWith('/api/v1/')) return p.slice('/api/v1'.length)
  return p
}

function parsePythonStringConstants(pyText) {
  const map = new Map()

  // Matches:
  //   NAME = "value"
  //   NAME: str = "value"
  // with optional trailing comment.
  const re =
    /^([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=\s*(?:\"([^\"]*)\"|'([^']*)')\s*(?:#.*)?$/gm
  let m
  while ((m = re.exec(pyText))) {
    const name = m[1]
    const value = m[2] ?? m[3] ?? ''
    map.set(name, value)
  }

  return map
}

export function parseBackendPrefixes() {
  const initPy = readText('app/api/v1/__init__.py')
  const constants = parsePythonStringConstants(initPy)
  const map = new Map()

  // Matches: router.include_router(documents.router, prefix="/documents", ...)
  const re = /include_router\(\s*([A-Za-z_][A-Za-z0-9_]*)\.router\b([\s\S]*?)\)/g
  let m
  while ((m = re.exec(initPy))) {
    const mod = m[1]
    const args = m[2] || ''
    const prefixMatch = args.match(/prefix\s*=\s*(?:\"([^\"]*)\"|'([^']*)')/)
    let prefix = prefixMatch ? (prefixMatch[1] || prefixMatch[2] || '') : ''
    if (!prefix) {
      const constMatch = args.match(/prefix\s*=\s*([A-Za-z_][A-Za-z0-9_]*)/)
      const constName = constMatch ? constMatch[1] : ''
      if (constName && constants.has(constName)) {
        prefix = constants.get(constName) || ''
      }
    }
    map.set(mod, prefix)
  }
  return map
}

function resolveBackendModuleRel(mod) {
  if (mod === 'kg') {
    return 'app/rag/kg/api/routes.py'
  }
  return `app/api/v1/${mod}.py`
}

function joinBackendPrefixes(parentPrefix, childPrefix) {
  const parent = String(parentPrefix || '').trim()
  const child = String(childPrefix || '').trim()
  if (!parent) return child
  if (!child) return parent
  return normalizeRoute(`${parent}/${child.replace(/^\/+/, '')}`)
}

function parseRouterIncludes(pyText) {
  const constants = parsePythonStringConstants(pyText)
  const includes = []

  const re = /router\.include_router\(\s*([A-Za-z_][A-Za-z0-9_]*)\.router\b([\s\S]*?)\)/g
  let m
  while ((m = re.exec(pyText))) {
    const mod = m[1]
    const args = m[2] || ''
    const prefixMatch = args.match(/prefix\s*=\s*(?:\"([^\"]*)\"|'([^']*)')/)
    let prefix = prefixMatch ? (prefixMatch[1] || prefixMatch[2] || '') : ''
    if (!prefix) {
      const constMatch = args.match(/prefix\s*=\s*([A-Za-z_][A-Za-z0-9_]*)/)
      const constName = constMatch ? constMatch[1] : ''
      if (constName && constants.has(constName)) {
        prefix = constants.get(constName) || ''
      }
    }
    includes.push({ mod, prefix })
  }

  const routesExtendRe =
    /_?router\.routes\.extend\(\s*([A-Za-z_][A-Za-z0-9_]*)\.router\.routes\s*\)/g
  while ((m = routesExtendRe.exec(pyText))) {
    includes.push({ mod: m[1], prefix: '' })
  }
  return includes
}

function parseRouterSelfPrefix(pyText) {
  const constants = parsePythonStringConstants(pyText)
  const re = /_?router\s*=\s*APIRouter\(([\s\S]*?)\)/m
  const match = re.exec(pyText)
  const args = match ? match[1] || '' : ''
  if (!args) return ''

  const prefixMatch = args.match(/prefix\s*=\s*(?:\"([^\"]*)\"|'([^']*)')/)
  if (prefixMatch) return prefixMatch[1] || prefixMatch[2] || ''

  const constMatch = args.match(/prefix\s*=\s*([A-Za-z_][A-Za-z0-9_]*)/)
  const constName = constMatch ? constMatch[1] : ''
  if (constName && constants.has(constName)) {
    return constants.get(constName) || ''
  }
  return ''
}

export function parseBackendRoutes() {
  const prefixes = parseBackendPrefixes()
  const routes = new Map() // key: METHOD PATH -> source

  const backendModules = []
  for (const [mod, prefix] of prefixes.entries()) {
    backendModules.push({ mod, prefix, rel: resolveBackendModuleRel(mod) })
  }

  const routeRe = /@router\.(get|post|put|patch|delete)\(\s*(?:\"([^\"]*)\"|'([^']*)')/g

  const seenModules = new Set()
  for (let index = 0; index < backendModules.length; index += 1) {
    const mod = backendModules[index]
    const seenKey = `${mod.rel}|${mod.prefix || ''}`
    if (seenModules.has(seenKey)) continue
    seenModules.add(seenKey)

    const abs = path.join(ROOT, mod.rel)
    if (!fs.existsSync(abs)) continue
    const text = fs.readFileSync(abs, 'utf8')
    const effectivePrefix = joinBackendPrefixes(mod.prefix, parseRouterSelfPrefix(text))
    let m
    while ((m = routeRe.exec(text))) {
      const method = String(m[1] || '').toUpperCase()
      const rawPath = m[2] ?? m[3] ?? ''
      const prefix = effectivePrefix || ''

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

    for (const child of parseRouterIncludes(text)) {
      backendModules.push({
        mod: child.mod,
        prefix: joinBackendPrefixes(effectivePrefix, child.prefix),
        rel: resolveBackendModuleRel(child.mod),
      })
    }
  }

  return routes
}

export function extractFrontendRoutesFromFile(rel) {
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

  // openapiRequest({ path: '/api/v1/...', method: 'get', ... })
  //
  // This is an incremental migration target for the web API client, so the
  // contract/coverage scripts must understand it.
  const openapiReqRe =
    /openapiRequest\(\s*\{[\s\S]*?\bpath\s*:\s*(?:`([^`]+)`|"([^"]+)"|'([^']+)')[\s\S]*?\bmethod\s*:\s*(?:`([^`]+)`|"([^"]+)"|'([^']+)')/g
  while ((m = openapiReqRe.exec(text))) {
    const rawPath = m[1] ?? m[2] ?? m[3] ?? ''
    const rawMethod = m[4] ?? m[5] ?? m[6] ?? ''
    const method = String(rawMethod || 'GET').toUpperCase()
    const normalized = normalizeRoute(rawPath)
    // Backend route parsing (from app/api/v1/*) does not include the /api/v1 prefix,
    // so strip it here for stable matching.
    out.push({ method, path: stripApiV1Prefix(normalized), src: rel })
  }

  // fetch/authenticatedFetch(`${API_V1_BASE_URL}/...`, { method: 'GET' })
  const fetchRe =
    /\b(?:fetch|authenticatedFetch)\(\s*`?\$\{API_V1_BASE_URL\}([^`"']+)`?\s*,\s*\{[\s\S]*?method\s*:\s*'([^']+)'/g
  while ((m = fetchRe.exec(text))) {
    const rawPath = m[1] || ''
    const method = String(m[2] || 'GET').toUpperCase()
    out.push({ method, path: normalizeRoute(rawPath), src: rel })
  }

  // fetch/authenticatedFetch(`${API_V1_BASE_URL}/...`) with default method GET
  const fetchNoOptsRe = /\b(?:fetch|authenticatedFetch)\(\s*`?\$\{API_V1_BASE_URL\}([^`"']+)`?\s*\)/g
  while ((m = fetchNoOptsRe.exec(text))) {
    const rawPath = m[1] || ''
    out.push({ method: 'GET', path: normalizeRoute(rawPath), src: rel })
  }

  return out
}

export function listFrontendSourceFiles() {
  const webRoot = path.join(ROOT, 'web')
  if (!fs.existsSync(webRoot)) return []

  const IGNORE_DIRS = new Set(['node_modules', '.next', '.next_build', 'out', 'dist', 'coverage'])

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

  walk(webRoot)
  return files
}

export function parseFrontendRoutes({ files } = {}) {
  const relFiles = Array.isArray(files) && files.length > 0 ? files : listFrontendSourceFiles()
  const routes = []
  for (const rel of relFiles) {
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
