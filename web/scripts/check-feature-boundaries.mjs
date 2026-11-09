/** Read-only feature dependency checks using the installed TypeScript parser. */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import ts from 'typescript'

function runtimeSpecifiers(file, source) {
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true)
  const imports = [], effects = []
  const line = node => tree.getLineAndCharacterOfPosition(node.getStart(tree)).line + 1
  const add = (node, specifier) => imports.push({ target: specifier, line: line(node) })
  const browserNames = new Set(['window', 'document', 'navigator', 'localStorage', 'sessionStorage', 'indexedDB', 'fetch', 'XMLHttpRequest', 'WebSocket'])
  function bound(node, name) {
    for (let scope = node.parent; scope; scope = scope.parent) {
      if (ts.isFunctionLike(scope) && scope.parameters.some(parameter => ts.isIdentifier(parameter.name) && parameter.name.text === name)) return true
      if (ts.isBlock(scope) || ts.isSourceFile(scope)) {
        if (scope.statements.some(statement => ts.isVariableStatement(statement) && statement.declarationList.declarations.some(declaration => ts.isIdentifier(declaration.name) && declaration.name.text === name))) return true
      }
    }
    return false
  }
  function visit(node) {
    if (ts.isImportDeclaration(node)) {
      const clause = node.importClause
      const onlyTypes = clause?.isTypeOnly || (clause && !clause.name && clause.namedBindings && ts.isNamedImports(clause.namedBindings) && clause.namedBindings.elements.every(element => element.isTypeOnly))
      if (!onlyTypes && ts.isStringLiteralLike(node.moduleSpecifier)) add(node, node.moduleSpecifier.text)
      return
    }
    if (ts.isExportDeclaration(node) && node.moduleSpecifier) {
      const onlyTypes = node.isTypeOnly || (node.exportClause && ts.isNamedExports(node.exportClause) && node.exportClause.elements.every(element => element.isTypeOnly))
      if (!onlyTypes && ts.isStringLiteralLike(node.moduleSpecifier)) add(node, node.moduleSpecifier.text)
      return
    }
    if (ts.isImportEqualsDeclaration(node) && !node.isTypeOnly && ts.isExternalModuleReference(node.moduleReference) && node.moduleReference.expression && ts.isStringLiteralLike(node.moduleReference.expression)) {
      add(node, node.moduleReference.expression.text)
      return
    }
    if (ts.isTypeNode(node)) return
    if (ts.isCallExpression(node) && (node.expression.kind === ts.SyntaxKind.ImportKeyword || ts.isIdentifier(node.expression) && node.expression.text === 'require') && node.arguments[0] && ts.isStringLiteralLike(node.arguments[0])) add(node, node.arguments[0].text)
    if (ts.isIdentifier(node) && browserNames.has(node.text) && !bound(node, node.text)) {
      const parent = node.parent
      const isName = (ts.isPropertyAccessExpression(parent) && parent.name === node)
        || ((ts.isVariableDeclaration(parent) || ts.isParameter(parent) || ts.isPropertyAssignment(parent) || ts.isMethodDeclaration(parent)) && parent.name === node)
      if (!isName) effects.push({ target: node.text, line: line(node) })
    }
    if (ts.isPropertyAccessExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'globalThis' && browserNames.has(node.name.text)) effects.push({ target: `globalThis.${node.name.text}`, line: line(node) })
    ts.forEachChild(node, visit)
  }
  visit(tree)
  return { imports, effects }
}

function resolveLocal(file, specifier, files) {
  const local = specifier.startsWith('@/') ? specifier.slice(2) : specifier.startsWith('.') ? path.posix.normalize(path.posix.join(path.posix.dirname(file), specifier)) : undefined
  if (local === undefined) return undefined
  const stem = local.replace(/\.[cm]?js$/, '')
  return [local, ...['.ts', '.tsx', '.js', '.mjs', '/index.ts', '/index.tsx'].map(extension => stem + extension)].find(candidate => files.has(candidate))
}

function forbiddenImport(target, role) {
  const local = target.replace(/^@\//, '')
  if (/^(?:@tanstack\/react-query|zustand)(?:\/|$)/.test(target) || /^(?:lib\/api(?:\/|\.tsx?$|$)|store\/)/.test(local)) return true
  return role === 'model' && (/^(?:react|react-dom|next)(?:\/|$)/.test(target) || /^(?:hooks\/)|\.(?:css|scss)$/.test(local))
}

export function inspectBoundaries(files, { models = [], views = [] } = {}) {
  const owners = new Map([...files.keys()].filter(file => /(?:^|\/)(?:[^/]+-)?model\.ts$/.test(file)).map(file => [file, 'model']))
  for (const model of models) owners.set(model, 'model')
  for (const view of views) owners.set(view, 'view')
  const facts = new Map(), violations = []
  function read(file) {
    if (!facts.has(file)) facts.set(file, runtimeSpecifiers(file, files.get(file)))
    return facts.get(file)
  }
  for (const [owner, role] of owners) {
    if (!files.has(owner)) throw new Error(`Registered ${role} does not exist: ${owner}`)
    const queue = [owner], visited = new Set()
    while (queue.length) {
      const file = queue.shift()
      if (visited.has(file)) continue
      visited.add(file)
      const { imports, effects } = read(file)
      for (const effect of effects) violations.push({ owner, file, rule: `${role}-effect`, ...effect })
      for (const edge of imports) {
        const resolved = resolveLocal(file, edge.target, files)
        const target = resolved ?? edge.target
        if (forbiddenImport(edge.target, role) || forbiddenImport(target, role) || role === 'model' && target.endsWith('.tsx')) {
          violations.push({ owner, file, rule: `${role}-import`, ...edge })
        } else if (resolved) queue.push(resolved)
        else if (/^(?:@\/|\.)/.test(edge.target) && !/\.(?:json|css|scss|svg)$/.test(edge.target)) violations.push({ owner, file, rule: 'unresolved-import', ...edge })
      }
    }
  }
  return violations
}

const identity = finding => JSON.stringify([finding.owner, finding.file, finding.rule, finding.target])

export function checkBaseline(findings, baseline) {
  const actual = new Map(), expected = new Map()
  const locations = new Map(findings.map(finding => [identity(finding), `${finding.file}:${finding.line}`]))
  for (const finding of findings) actual.set(identity(finding), (actual.get(identity(finding)) ?? 0) + 1)
  for (const row of baseline) {
    const key = identity(row)
    if (expected.has(key) || !row.task || row.count <= 0) throw new Error(`Invalid migration entry: ${key}`)
    expected.set(key, row.count)
  }
  return [...new Set([...actual.keys(), ...expected.keys()])].sort().flatMap(key => {
    const count = actual.get(key) ?? 0, allowed = expected.get(key) ?? 0
    return count === allowed ? [] : [`${count > allowed ? 'new' : 'stale'}: ${locations.get(key) ?? 'removed edge'} ${key} (${count}, baseline ${allowed})`]
  })
}

export function scanWeb(root) {
  const files = new Map()
  function walk(directory) {
    for (const entry of fs.readdirSync(path.join(root, directory), { withFileTypes: true })) {
      const file = path.posix.join(directory, entry.name)
      if (entry.isDirectory()) walk(file)
      else if (/\.[cm]?[jt]sx?$/.test(file) && !/\.(?:test|spec|d)\.[cm]?[jt]sx?$/.test(file)) files.set(file, fs.readFileSync(path.join(root, file), 'utf8'))
    }
  }
  for (const directory of ['app', 'components', 'hooks', 'lib', 'store', 'types']) walk(directory)
  const roles = JSON.parse(fs.readFileSync(path.join(root, 'scripts/feature-boundaries.json'), 'utf8'))
  return inspectBoundaries(files, roles)
}

function main() {
  const args = process.argv.slice(2)
  const rootIndex = args.indexOf('--root')
  const root = rootIndex < 0 ? fileURLToPath(new URL('..', import.meta.url)) : path.resolve(args[rootIndex + 1])
  const findings = scanWeb(root)
  if (args.includes('--inventory')) { process.stdout.write(`${JSON.stringify(findings, null, 2)}\n`); return }
  const baseline = JSON.parse(fs.readFileSync(path.join(root, 'scripts/feature-boundary-baseline.json'), 'utf8'))
  const errors = checkBaseline(findings, baseline)
  for (const error of errors) process.stderr.write(`${error}\n`)
  if (!errors.length) process.stdout.write(`Feature boundaries OK; ${findings.length} explicitly tracked migration edges\n`)
  process.exitCode = errors.length ? 1 : 0
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) main()
