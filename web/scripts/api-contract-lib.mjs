import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
// This script lives under web/scripts/. Repo root is two levels up.
const ROOT = path.resolve(__dirname, '../..')
const API_CLIENT_METHODS = new Set(['get', 'post', 'put', 'patch', 'delete'])

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
  const re = /^([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=\s*(?:\"([^\"]*)\"|'([^']*)')\s*(?:#.*)?$/gm
  let m
  while ((m = re.exec(pyText))) {
    const name = m[1]
    const value = m[2] ?? m[3] ?? ''
    map.set(name, value)
  }

  return map
}

export function parseBackendModuleImports(source, ownerRel) {
  const imports = new Map()
  const text = source.replace(/#[^\n]*/g, '')
  function modulePath(name) {
    if (!name.startsWith('.')) return name.replaceAll('.', '/')
    const relative = name.match(/^(\.+)(.*)$/)
    return path.posix.join(
      path.posix.dirname(ownerRel),
      ...Array(relative[1].length - 1).fill('..'),
      relative[2].replaceAll('.', '/'),
    )
  }
  const directImports = /^\s*import\s+([A-Za-z_][\w.]*)\s+as\s+([A-Za-z_]\w*)\s*$/gm
  for (const match of text.matchAll(directImports)) imports.set(match[2], modulePath(match[1]))
  const fromImports = /^\s*from\s+([.\w]+)\s+import\s+(?:\(([\s\S]*?)\)|([^\n]+))/gm
  for (const match of text.matchAll(fromImports)) {
    const parent = modulePath(match[1])
    for (const item of (match[2] ?? match[3]).split(',')) {
      const imported = item.trim().match(/^([A-Za-z_]\w*)(?:\s+as\s+([A-Za-z_]\w*))?$/)
      if (imported !== null) imports.set(imported[2] ?? imported[1], path.posix.join(parent, imported[1]))
    }
  }
  return imports
}

function resolveBackendModuleRel(alias, imports, ownerRel) {
  const imported = imports.get(alias)
  if (imported === undefined) throw new Error(`Cannot resolve registered router ${alias} in ${ownerRel}`)
  const candidates = [`${imported}.py`, `${imported}/__init__.py`]
  const resolved = candidates.find((candidate) => fs.existsSync(path.join(ROOT, candidate)))
  if (resolved === undefined) throw new Error(`Missing registered router module ${imported} in ${ownerRel}`)
  return resolved
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
    let prefix = prefixMatch ? prefixMatch[1] || prefixMatch[2] || '' : ''
    if (!prefix) {
      const constMatch = args.match(/prefix\s*=\s*([A-Za-z_][A-Za-z0-9_]*)/)
      const constName = constMatch ? constMatch[1] : ''
      if (constName && constants.has(constName)) {
        prefix = constants.get(constName) || ''
      }
    }
    includes.push({ mod, prefix })
  }

  const routesExtendRe = /_?router\.routes\.extend\(\s*([A-Za-z_][A-Za-z0-9_]*)\.router\.routes\s*\)/g
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

export function parseBackendRoutes({ schemaOnly = false } = {}) {
  const rootRel = 'app/api/v1/__init__.py'
  const rootSource = readText(rootRel)
  const rootImports = parseBackendModuleImports(rootSource, rootRel)
  const routes = new Map() // key: METHOD PATH -> source

  const backendModules = parseRouterIncludes(rootSource).map(({ mod, prefix }) => ({
    prefix,
    rel: resolveBackendModuleRel(mod, rootImports, rootRel),
  }))

  const routeRe =
    /@router\.(get|post|put|patch|delete)\(\s*(?:"([^"]*)"|'([^']*)')([\s\S]*?)(?=^\s*(?:@|(?:async )?def\s))/gm

  const seenModules = new Set()
  for (let index = 0; index < backendModules.length; index += 1) {
    const mod = backendModules[index]
    const seenKey = `${mod.rel}|${mod.prefix || ''}`
    if (seenModules.has(seenKey)) continue
    seenModules.add(seenKey)

    const abs = path.join(ROOT, mod.rel)
    const text = fs.readFileSync(abs, 'utf8')
    const imports = parseBackendModuleImports(text, mod.rel)
    const effectivePrefix = joinBackendPrefixes(mod.prefix, parseRouterSelfPrefix(text))
    for (const [, rawMethod, doubleQuotedPath, singleQuotedPath, routeOptions] of text.matchAll(routeRe)) {
      if (schemaOnly && /,\s*include_in_schema\s*=\s*False\s*[,)]/.test(routeOptions)) continue
      const method = rawMethod.toUpperCase()
      const routePath = doubleQuotedPath ?? singleQuotedPath
      const normalized = normalizeRoute(joinBackendPrefixes(effectivePrefix, routePath))
      const key = `${method} ${normalized}`
      routes.set(key, mod.rel)
    }

    for (const child of parseRouterIncludes(text)) {
      backendModules.push({
        prefix: joinBackendPrefixes(effectivePrefix, child.prefix),
        rel: resolveBackendModuleRel(child.mod, imports, mod.rel),
      })
    }
  }

  return routes
}

export function extractFrontendRoutesFromFile(rel) {
  const abs = path.join(ROOT, rel)
  const text = fs.readFileSync(abs, 'utf8')
  const out = []

  const source = ts.createSourceFile(rel, text, ts.ScriptTarget.Latest)
  function collectRoutes(node) {
    ts.forEachChild(node, collectRoutes)
    if (!ts.isCallExpression(node)) return
    if (ts.isIdentifier(node.expression) && ['fetch', 'authenticatedFetch'].includes(node.expression.text)) {
      const [route, options] = node.arguments
      if (route === undefined || !ts.isTemplateExpression(route) || route.head.text !== '') return
      const [base, ...spans] = route.templateSpans
      if (!ts.isIdentifier(base.expression) || base.expression.text !== 'API_V1_BASE_URL') return
      if (options !== undefined && !ts.isObjectLiteralExpression(options)) return

      let method = 'GET'
      for (const property of options?.properties ?? []) {
        if (ts.isSpreadAssignment(property)) {
          method = undefined
          continue
        }
        if ((ts.isIdentifier(property.name) || ts.isStringLiteral(property.name)) && property.name.text === 'method') {
          method =
            ts.isPropertyAssignment(property) && ts.isStringLiteralLike(property.initializer)
              ? property.initializer.text.toUpperCase()
              : undefined
        }
      }
      const rawPath = base.literal.text + spans.map((span) => `{}${span.literal.text}`).join('')
      if (method !== undefined) out.push({ method, path: normalizeRoute(rawPath), src: rel })
      return
    }
    if (!ts.isPropertyAccessExpression(node.expression)) return
    const { expression: client, name } = node.expression
    if (!ts.isIdentifier(client) || client.text !== 'apiClient' || !API_CLIENT_METHODS.has(name.text)) return
    const route = node.arguments[0]
    if (route === undefined) return
    let rawPath
    if (ts.isStringLiteralLike(route)) {
      rawPath = route.text
    } else if (ts.isTemplateExpression(route)) {
      rawPath = route.head.text + route.templateSpans.map((span) => `{}${span.literal.text}`).join('')
    }
    if (rawPath === undefined || rawPath === '') return
    out.push({ method: name.text.toUpperCase(), path: normalizeRoute(rawPath), src: rel })
  }
  collectRoutes(source)

  // openapiRequest({ path: '/api/v1/...', method: 'get', ... })
  //
  // This is an incremental migration target for the web API client, so the
  // contract/coverage scripts must understand it.
  const openapiReqRe =
    /openapiRequest\(\s*\{[\s\S]*?\bpath\s*:\s*(?:`([^`]+)`|"([^"]+)"|'([^']+)')[\s\S]*?\bmethod\s*:\s*(?:`([^`]+)`|"([^"]+)"|'([^']+)')/g
  let m
  while ((m = openapiReqRe.exec(text))) {
    const rawPath = m[1] ?? m[2] ?? m[3] ?? ''
    const rawMethod = m[4] ?? m[5] ?? m[6] ?? ''
    const method = String(rawMethod || 'GET').toUpperCase()
    const normalized = normalizeRoute(rawPath)
    // Backend route parsing (from app/api/v1/*) does not include the /api/v1 prefix,
    // so strip it here for stable matching.
    out.push({ method, path: stripApiV1Prefix(normalized), src: rel })
  }

  return out
}

export function listFrontendSourceFiles() {
  const webRoot = path.join(ROOT, 'web')

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
      const rel = path.relative(ROOT, abs).replaceAll(path.sep, '/')
      files.push(rel)
    }
  }

  walk(webRoot)
  return files
}

export function parseFrontendRoutes({ files = listFrontendSourceFiles() } = {}) {
  const routes = []
  for (const rel of files) {
    routes.push(...extractFrontendRoutesFromFile(rel))
  }

  // Dedup
  const uniq = new Map()
  for (const r of routes) {
    const key = `${r.method} ${r.path}`
    if (!uniq.has(key)) uniq.set(key, r)
  }
  return Array.from(uniq.values())
}
