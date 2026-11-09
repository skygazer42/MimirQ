import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { buildStructuralReviews } from './audit-structural-rules.mjs'

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const arguments_ = process.argv.slice(2)
const fixIdentityCasts = arguments_.includes('--fix-identity-casts')
const fixRedundantDefaults = arguments_.includes('--fix-redundant-defaults')
const output = path.resolve(repository, arguments_.find(argument => !argument.startsWith('--')) || 'artifacts/code-style/full-audit-v2/frontend-automatic.json')
const skipDirectories = new Set(['node_modules', 'build', 'dist', 'out', 'coverage', 'test-results', 'playwright-report', '.git', '.docusaurus'])
const codeExtension = /\.(?:[cm]?js|jsx|[cm]?ts|tsx)$/i
const sources = []
const generatedSources = []
const inventory = []

function walk(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!skipDirectories.has(entry.name) && !entry.name.startsWith('.next')) walk(path.join(directory, entry.name))
      continue
    }
    if (!entry.isFile()) continue
    const absolute = path.join(directory, entry.name)
    const relative = path.relative(repository, absolute).replaceAll('\\', '/')
    if (/\.(?:tsbuildinfo|lock)$/i.test(relative) || /(?:^|\/)(?:package-lock|pnpm-lock|yarn\.lock)/.test(relative)) continue
    const content = fs.readFileSync(absolute)
    const generated = relative === 'web/types/openapi.ts' || relative === 'web/next-env.d.ts' || relative.startsWith('web/public/') || relative.startsWith('docs-site/static/')
    const executable = codeExtension.test(relative)
    const record = {
      path: relative,
      bytes: content.length,
      sha256: crypto.createHash('sha256').update(content).digest('hex'),
      category: generated ? 'generated-or-static-asset' : executable ? 'executable-source' : /\.(?:css|scss|less|html|mdx)$/i.test(relative) ? 'presentation-source' : 'configuration-document-or-data',
      parser: executable && !generated ? 'typescript-compiler-api' : null,
      findings: [],
    }
    inventory.push(record)
    if (executable && !generated) sources.push({ absolute, record })
    if (executable && generated && !relative.endsWith('.d.ts') && relative !== 'web/types/openapi.ts') generatedSources.push({ absolute, record })
  }
}

walk(path.join(repository, 'web'))
walk(path.join(repository, 'docs-site'))
// The root audit supplies the authoritative non-generated project inventory.
// Its remaining JavaScript files are reviewed read-only by this same compiler.
const globalInventoryPath = path.join(repository, 'artifacts/code-style/full-audit-v2/initial-inventory.json')
if (fs.existsSync(globalInventoryPath)) {
  const globalFiles = JSON.parse(fs.readFileSync(globalInventoryPath, 'utf8'))
  for (const relative of globalFiles.filter(file => codeExtension.test(file) && !/^(?:web|docs-site)\//.test(file))) {
    const absolute = path.join(repository, relative)
    const content = fs.readFileSync(absolute)
    const record = { path: relative, bytes: content.length, sha256: crypto.createHash('sha256').update(content).digest('hex'), category: 'executable-source-read-only-outside-frontend', parser: 'typescript-compiler-api', findings: [] }
    inventory.push(record)
    sources.push({ absolute, record })
  }
}
const configFile = ts.readConfigFile(path.join(repository, 'web/tsconfig.json'), ts.sys.readFile)
if (configFile.error) throw new Error(ts.flattenDiagnosticMessageText(configFile.error.messageText, '\n'))
const parsedConfig = ts.parseJsonConfigFileContent(configFile.config, ts.sys, path.join(repository, 'web'))
const program = ts.createProgram(sources.map(({ absolute }) => absolute), { ...parsedConfig.options, allowJs: true, checkJs: false, incremental: false, noEmit: true })
const checker = program.getTypeChecker()
const structuralReviews = buildStructuralReviews(sources.map(({ absolute }) => program.getSourceFile(absolute)), checker, repository)
const counts = {}
const transformations = []

// These files interpret browser/storage/security protocol data. Their runtime
// contracts receive manual review even when an asserted type appears precise.
const runtimeBoundaries = /(?:^web\/app\/api\/|^web\/lib\/(?:api-errors|auth-storage|authenticated-fetch|doc-(?:content|source)-cache|image-auth-proxy|markdown-image-proxy(?:-token)?|oidc(?:-.*)?|openapi-request|saml-session|server-auth-route|api\/core)\.[cm]?tsx?$|^web\/store\/)/

function identityArgumentText(node, sourceFile) {
  return expressionText(node.arguments[0], sourceFile)
}

function expressionText(argument, sourceFile) {
  const raw = argument.getText(sourceFile)
  return ts.isIdentifier(argument) || ts.isPropertyAccessExpression(argument) || ts.isElementAccessExpression(argument) || ts.isCallExpression(argument) || ts.isLiteralExpression(argument) || ts.isParenthesizedExpression(argument)
    ? raw
    : `(${raw})`
}

function flagsIn(type, flags) {
  return type.isUnion() ? type.types.some(member => flagsIn(member, flags)) : Boolean(type.flags & flags)
}

function known(type) {
  return !flagsIn(type, ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.Never | ts.TypeFlags.TypeParameter)
}

function nonNullish(type) {
  return known(type) && !flagsIn(type, ts.TypeFlags.Null | ts.TypeFlags.Undefined | ts.TypeFlags.Void)
}

function everyType(type, flags) {
  return type.isUnion() ? type.types.every(member => everyType(member, flags)) : Boolean(type.flags & flags)
}

function containsUncheckedIndex(node, seen = new Set()) {
  if (ts.isElementAccessExpression(node)) return true
  if (ts.isPropertyAccessExpression(node)) {
    const container = checker.getTypeAtLocation(node.expression)
    if (!checker.getPropertyOfType(container, node.name.text) && checker.getIndexTypeOfType(container, ts.IndexKind.String)) return true
    return containsUncheckedIndex(node.expression, seen)
  }
  if (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isNonNullExpression(node)) return containsUncheckedIndex(node.expression, seen)
  if (ts.isBinaryExpression(node) || ts.isConditionalExpression(node)) {
    const children = []
    ts.forEachChild(node, child => { children.push(child) })
    return children.some(child => containsUncheckedIndex(child, seen))
  }
  if (ts.isIdentifier(node)) {
    const symbol = checker.getSymbolAtLocation(node)
    if (!symbol || seen.has(symbol)) return false
    seen.add(symbol)
    return (symbol.declarations || []).some(declaration => {
      if (ts.isBindingElement(declaration)) return true
      return ts.isVariableDeclaration(declaration) && declaration.initializer && containsUncheckedIndex(declaration.initializer, seen)
    })
  }
  return false
}

function describe(node, sourceFile) {
  return node.getText(sourceFile).replace(/\s+/g, ' ').slice(0, 300)
}

for (const { absolute, record } of sources) {
  const sourceFile = program.getSourceFile(absolute)
  if (!sourceFile) throw new Error(`Source file missing from compiler program: ${record.path}`)
  record.structuralReview = structuralReviews.get(record.path)
  record.syntaxErrors = sourceFile.parseDiagnostics.map(diagnostic => ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n'))
  const identityEdits = []
  const defaultEdits = []
  function add(kind, node, value, note) {
    const point = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile))
    const type = value ? checker.getTypeAtLocation(value) : null
    const uncheckedIndex = value ? containsUncheckedIndex(value) : false
    const finding = {
      kind,
      line: point.line + 1,
      column: point.character + 1,
      start: node.getStart(sourceFile),
      end: node.end,
      source: describe(node, sourceFile),
      value: value ? describe(value, sourceFile) : null,
      type: type ? checker.typeToString(type) : null,
      uncheckedIndex,
      provenance: 'automatic-ast-typechecker-candidate-requires-call-chain-review',
      note,
    }
    record.findings.push(finding)
    counts[kind] = (counts[kind] || 0) + 1
  }
  function visit(node) {
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken) {
      const type = checker.getTypeAtLocation(node.left)
      if (nonNullish(type)) add('required-nullish-default', node, node.left, 'Type excludes null/undefined; indexed reads and external/runtime contracts still need review.')
    }
    if (ts.isBinaryExpression(node)) {
      const type = checker.getTypeAtLocation(node.left)
      const primitive = ts.TypeFlags.StringLike | ts.TypeFlags.NumberLike | ts.TypeFlags.BooleanLike | ts.TypeFlags.BigIntLike
      const nullishIdentity = node.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken && nonNullish(type) && everyType(type, primitive)
      const falsyIdentity = node.operatorToken.kind === ts.SyntaxKind.BarBarToken && known(type) && ((ts.isStringLiteral(node.right) && node.right.text === '' && everyType(type, ts.TypeFlags.StringLike)) || (node.right.kind === ts.SyntaxKind.FalseKeyword && everyType(type, ts.TypeFlags.BooleanLike)))
      if (falsyIdentity) add('typed-falsy-identity-default', node, node.left, 'Empty string or false fallback is an identity for the required primitive type.')
      const boundary = runtimeBoundaries.test(record.path) || !/^(?:web|docs-site)\//.test(record.path) || /\b(?:globalThis|window|document|navigator|crypto|performance)\b/.test(node.left.getText(sourceFile))
      if ((nullishIdentity || falsyIdentity) && !boundary && !containsUncheckedIndex(node.left) && !ts.isCallExpression(node.left) && !/\/\*|\/\//.test(node.getText(sourceFile))) {
        defaultEdits.push({ start: node.getStart(sourceFile), end: node.end, replacement: expressionText(node.left, sourceFile), rule: 'redundant-primitive-default' })
      }
    }
    if ((ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node) || ts.isCallExpression(node)) && node.questionDotToken) {
      const type = checker.getTypeAtLocation(node.expression)
      if (nonNullish(type)) add('required-optional-chain', node, node.expression, 'Expression is required in the current control-flow type; verify initialization, indexed reads and external contracts.')
    }
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.expression.getText(sourceFile) === 'Array' && node.expression.name.text === 'isArray' && node.arguments.length === 1) {
      const type = checker.getTypeAtLocation(node.arguments[0])
      if (known(type) && (checker.isArrayType(type) || checker.isTupleType(type))) add('typed-array-validation', node, node.arguments[0], 'Array type is already declared; verify callers and external input before removing runtime validation.')
    }
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.arguments.length === 1) {
      const target = { String: ts.TypeFlags.StringLike, Number: ts.TypeFlags.NumberLike, Boolean: ts.TypeFlags.BooleanLike }[node.expression.text]
      const type = checker.getTypeAtLocation(node.arguments[0])
      if (target && known(type) && everyType(type, target)) {
        add('identity-primitive-cast', node, node.arguments[0], 'Primitive cast is an identity for the declared type; verify source contract.')
        const declarationFile = checker.getResolvedSignature(node)?.declaration?.getSourceFile().fileName.replaceAll('\\', '/')
        const globalPrimitiveConstructor = declarationFile?.endsWith('/typescript/lib/lib.es5.d.ts')
        // Dataset pagination deliberately treats malformed totals as untrusted;
        // its focused tests exercise this external response boundary.
        const malformedTotalBoundary = record.path === 'web/lib/api/datasets.ts' && node.arguments[0].getText(sourceFile) === 'page.total'
        const eligible = globalPrimitiveConstructor && /^(?:web|docs-site)\//.test(record.path) && !runtimeBoundaries.test(record.path) && !malformedTotalBoundary && !containsUncheckedIndex(node.arguments[0]) && !/\/\*|\/\//.test(node.getText(sourceFile))
        record.findings.at(-1).automaticIdentityEditEligible = eligible
        if (eligible) identityEdits.push({ start: node.getStart(sourceFile), end: node.end, replacement: identityArgumentText(node, sourceFile), rule: 'identity-primitive-cast' })
      }
    }
    if (ts.isBinaryExpression(node) && ts.isTypeOfExpression(node.left) && ts.isStringLiteral(node.right)) {
      const target = { string: ts.TypeFlags.StringLike, number: ts.TypeFlags.NumberLike, boolean: ts.TypeFlags.BooleanLike, bigint: ts.TypeFlags.BigIntLike, symbol: ts.TypeFlags.ESSymbolLike }[node.right.text]
      const type = checker.getTypeAtLocation(node.left.expression)
      if (target && known(type) && everyType(type, target)) add('typed-primitive-validation', node, node.left.expression, 'Primitive type already declared; boundary parsers must retain runtime checks.')
    }
    if (ts.isCatchClause(node)) add('catch-review', node, null, 'Review whether failure is observable, cleanup, security fail-closed or documented optional-feature degradation.')
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === 'catch') add('promise-catch-review', node, null, 'Review rejection handling and documented abort/optional/lifecycle behavior.')
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  const requestedEdits = [...(fixIdentityCasts ? identityEdits : []), ...(fixRedundantDefaults ? defaultEdits : [])]
  if (requestedEdits.length) {
    // Keep the deepest candidates on this pass so no overlapping edit can
    // discard another change. A later scan reports any remaining outer cast.
    const independent = requestedEdits.filter(edit => !requestedEdits.some(other => other.start >= edit.start && other.end <= edit.end && (other.start !== edit.start || other.end !== edit.end)))
    const original = fs.readFileSync(absolute, 'utf8')
    if (crypto.createHash('sha256').update(original).digest('hex') !== record.sha256) throw new Error(`Concurrent change detected: ${record.path}`)
    const backup = path.join(repository, 'artifacts/code-style/full-audit-v2/frontend-before', record.path)
    fs.mkdirSync(path.dirname(backup), { recursive: true })
    if (!fs.existsSync(backup)) fs.writeFileSync(backup, original)
    let updated = original
    for (const edit of independent.sort((a, b) => b.start - a.start)) updated = updated.slice(0, edit.start) + edit.replacement + updated.slice(edit.end)
    const verificationSource = ts.createSourceFile(absolute, updated, ts.ScriptTarget.Latest, true, sourceFile.scriptKind)
    if (verificationSource.parseDiagnostics.length) throw new Error(`Refusing syntactically invalid edits: ${record.path}`)
    fs.writeFileSync(absolute, updated)
    transformations.push({ path: record.path, rules: [...new Set(independent.map(edit => edit.rule))], edits: independent.length, beforeSha256: record.sha256, afterSha256: crypto.createHash('sha256').update(updated).digest('hex') })
    for (const finding of record.findings) {
      if (independent.some(edit => edit.start === finding.start && edit.end === finding.end)) finding.action = 'simplified-proven-primitive-identity'
    }
  }
}

function syntaxBoundaryReview(sourceFile) {
  const summary = { astNodes: 0, catchClauses: 0, optionalChains: 0, defaultExpressions: 0, arrayChecks: 0 }
  function visit(node) {
    summary.astNodes += 1
    if (ts.isCatchClause(node)) summary.catchClauses += 1
    if (node.questionDotToken) summary.optionalChains += 1
    if (ts.isBinaryExpression(node) && (node.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken || node.operatorToken.kind === ts.SyntaxKind.BarBarToken)) summary.defaultExpressions += 1
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.expression.getText(sourceFile) === 'Array' && node.expression.name.text === 'isArray') summary.arrayChecks += 1
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  return { ...summary, syntaxErrors: sourceFile.parseDiagnostics.map(diagnostic => ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n')) }
}

for (const { absolute, record } of generatedSources) {
  const sourceFile = ts.createSourceFile(absolute, fs.readFileSync(absolute, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  record.parser = 'typescript-compiler-api-syntax-only-generated-boundary'
  record.generatedBoundaryReview = syntaxBoundaryReview(sourceFile)
  record.reviewLimit = 'Generated/bundled static executable: AST detection only; no runtime type or behavior claims and no edits.'
}

for (const record of inventory.filter(file => file.path.endsWith('.html'))) {
  const html = fs.readFileSync(path.join(repository, record.path), 'utf8')
  record.embeddedScripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi)].map((match, index) => {
    const source = /\bsrc\s*=\s*["']([^"']+)["']/i.exec(match[1])?.[1]
    const data = /\btype\s*=\s*["'](?:application\/(?:ld\+)?json|importmap)["']/i.test(match[1])
    if (source || data) return { index, category: source ? 'external-script-reference' : 'non-executable-json-data', source: source || null }
    const sourceFile = ts.createSourceFile(`${record.path}#script-${index}.js`, match[2], ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
    return { index, category: 'generated-static-inline-script-boundary', parser: 'typescript-compiler-api-syntax-only', ...syntaxBoundaryReview(sourceFile), reviewLimit: 'Embedded static script parsed automatically; runtime contract and behavior not verified.' }
  })
}

const result = {
  generatedAt: new Date().toISOString(),
  scope: ['web', 'docs-site', 'all other executable JavaScript/TypeScript in the root project inventory (read-only)'],
  method: 'Complete directory inventory; TypeScript compiler AST and strict web compiler typechecker for every executable source outside generated/static/dependency/build output. Findings are candidates, never automatic proof of safe edits.',
  exclusions: [...skipDirectories, '.next*', 'dependency lock files', 'tsbuildinfo'],
  summary: { inventoriedFiles: inventory.length, parsedSources: sources.length, generatedExecutablesSyntaxParsed: generatedSources.length, htmlFilesWithEmbeddedScriptInventory: inventory.filter(file => file.embeddedScripts).length, findings: counts },
  transformations,
  files: inventory.sort((a, b) => a.path.localeCompare(b.path)),
}
fs.mkdirSync(path.dirname(output), { recursive: true })
fs.writeFileSync(output, `${JSON.stringify(result, null, 2)}\n`)
console.log(JSON.stringify({ output: path.relative(repository, output).replaceAll('\\', '/'), ...result.summary }))
