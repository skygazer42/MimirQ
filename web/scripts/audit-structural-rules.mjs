import path from 'node:path'
import ts from 'typescript'

const genericHelperName = /^(?:coerce|normalize|safe|as(?:Record|Object|Finite|String|Number)|to(?:Finite|String|Number|Optional|Int)|read(?:String|Number))/
const controls = node => ts.isIfStatement(node) || ts.isConditionalExpression(node) || ts.isIterationStatement(node, false) || ts.isSwitchStatement(node) || ts.isTryStatement(node)
const isFunction = node => ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) || ts.isArrowFunction(node) || ts.isMethodDeclaration(node)
const relative = (repository, file) => path.relative(repository, file).replaceAll('\\', '/')

function unwrap(expression) {
  while (ts.isParenthesizedExpression(expression)) expression = expression.expression
  return expression
}

function terminal(statement) {
  if (ts.isReturnStatement(statement) || ts.isThrowStatement(statement)) return true
  if (ts.isBlock(statement)) return statement.statements.length > 0 && terminal(statement.statements.at(-1))
  return ts.isIfStatement(statement) && statement.elseStatement && terminal(statement.thenStatement) && terminal(statement.elseStatement)
}

function primitiveFamily(type) {
  if (type.isUnion()) {
    const families = type.types.map(primitiveFamily).filter(family => family !== 'absent')
    return families.length && families.every(family => family === families[0]) ? families[0] : 'mixed-or-unknown'
  }
  if (type.flags & (ts.TypeFlags.Null | ts.TypeFlags.Undefined | ts.TypeFlags.Void)) return 'absent'
  if (type.flags & ts.TypeFlags.NumberLike) return 'number'
  if (type.flags & ts.TypeFlags.StringLike) return 'string'
  if (type.flags & ts.TypeFlags.BooleanLike) return 'boolean'
  return 'mixed-or-unknown'
}

function functionName(node, sourceFile) {
  if (node.name) return node.name.getText(sourceFile)
  if (ts.isVariableDeclaration(node.parent)) return node.parent.name.getText(sourceFile)
  return '<callback>'
}

function onlyExit(statement) {
  if (ts.isBlock(statement)) {
    if (statement.statements.length !== 1) return null
    statement = statement.statements[0]
  }
  if (!ts.isReturnStatement(statement) && !ts.isThrowStatement(statement)) return null
  return /[\r\n]/.test(statement.getText()) ? null : statement
}

/** Safe only in a statement list, with no declarations/effects in branch blocks. */
export function collectPureReturnLadderEdits(sourceFile) {
  const candidates = []
  function ladder(node) {
    if (!ts.isIfStatement(node) || !node.elseStatement) return null
    if (/[\r\n]/.test(node.expression.getText(sourceFile))) return null
    const exit = onlyExit(node.thenStatement)
    if (!exit) return null
    const finalExit = onlyExit(node.elseStatement)
    const remaining = finalExit ? finalExit.getText(sourceFile) : ladder(node.elseStatement)
    if (!remaining) return null
    return `if (${node.expression.getText(sourceFile)}) ${exit.getText(sourceFile)}\n${remaining}`
  }
  function visit(node) {
    if (ts.isIfStatement(node) && (ts.isBlock(node.parent) || ts.isSourceFile(node.parent) || ts.isCaseClause(node.parent) || ts.isDefaultClause(node.parent))) {
      const replacement = ladder(node)
      if (replacement && !/\/\*|\/\//.test(node.getText(sourceFile))) {
        const start = node.getStart(sourceFile)
        const lineStart = sourceFile.getPositionOfLineAndCharacter(sourceFile.getLineAndCharacterOfPosition(start).line, 0)
        const indent = sourceFile.text.slice(lineStart, start).match(/^\s*/)[0]
        candidates.push({ start, end: node.end, replacement: replacement.replaceAll('\n', `\n${indent}`), line: sourceFile.getLineAndCharacterOfPosition(start).line + 1, rule: 'pure-return-ladder-to-flat-guards' })
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  return candidates.filter(edit => !candidates.some(inner => inner.start >= edit.start && inner.end <= edit.end && (inner.start !== edit.start || inner.end !== edit.end)))
}

/** Structural findings are review candidates. No lexical scope is rewritten. */
export function buildStructuralReviews(sourceFiles, checker, repository) {
  const results = new Map()
  const functions = new Map()
  const details = new Map()
  for (const sourceFile of sourceFiles) {
    const filename = relative(repository, sourceFile.fileName)
    const record = { method: 'complete-function-control-flow-and-direct-callsite-ast-pass', astNodes: 0, functions: [], candidates: [] }
    results.set(filename, record)
    record.pureReturnLadderEdits = collectPureReturnLadderEdits(sourceFile).map(({ line, rule }) => ({ line, rule, action: 'lexically-safe-candidate; baseline-and-current-ownership-still-required' }))
    const site = (kind, node, evidence) => {
      record.candidates.push({ kind, line: sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1, source: node.getText(sourceFile).replace(/\s+/g, ' ').slice(0, 240), evidence, action: 'requires-call-chain-and-lexical-scope-review' })
    }
    function visit(node, enclosingFunction, depth) {
      record.astNodes += 1
      if (isFunction(node)) {
        const info = { name: functionName(node, sourceFile), line: sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1, parameterTypes: node.parameters.map(parameter => ({ name: parameter.name.getText(sourceFile), type: checker.typeToString(checker.getTypeAtLocation(parameter)), broad: Boolean(checker.getTypeAtLocation(parameter).flags & (ts.TypeFlags.Unknown | ts.TypeFlags.Any)) })), branches: 0, maxControlDepth: 0, typeChecks: 0, catches: 0, directCalls: [] }
        record.functions.push(info)
        functions.set(node, info)
        details.set(node, { record, site, sourceFile })
        enclosingFunction = node
        depth = 0
      }
      const info = functions.get(enclosingFunction)
      if (controls(node)) {
        depth += 1
        if (info) { info.branches += 1; info.maxControlDepth = Math.max(info.maxControlDepth, depth) }
      }
      if (ts.isTypeOfExpression(node) && info) info.typeChecks += 1
      if (ts.isCatchClause(node)) {
        if (info) info.catches += 1
        const fallback = node.block.statements.find(statement => ts.isReturnStatement(statement))
        if (fallback) site('catch-to-return-fallback', node, 'A caught failure returns a value; verify whether it hides an internal invariant or is a documented external/optional failure boundary.')
      }
      if (ts.isIfStatement(node)) {
        if (node.elseStatement && terminal(node.thenStatement)) site('else-after-terminal-branch', node, 'The successful branch exits. A guard clause may remove else nesting, but block-local declarations must retain lexical scope.')
        const statements = ts.isBlock(node.thenStatement) ? node.thenStatement.statements : [node.thenStatement]
        if (!node.elseStatement && statements.length === 1 && ts.isIfStatement(statements[0]) && !statements[0].elseStatement) site('nested-single-condition', node, 'The body only contains another condition; inspect whether a combined condition or early guard reads more directly.')
      }
      if (ts.isCallExpression(node)) {
        const expression = unwrap(node.expression)
        if ((ts.isArrowFunction(expression) || ts.isFunctionExpression(expression)) && ts.isBlock(expression.body)) site('immediate-function-wrapper', node, 'An immediately invoked function creates a return/scope layer; inspect direct mapping, a named domain function, or a guard sequence. Do not blindly unwrap lexical scope.')
      }
      ts.forEachChild(node, child => visit(child, enclosingFunction, depth))
    }
    visit(sourceFile, null, 0)
  }
  for (const sourceFile of sourceFiles) {
    function visit(node) {
      if (ts.isCallExpression(node)) {
        const declaration = checker.getResolvedSignature(node)?.declaration
        const info = functions.get(declaration)
        if (info) info.directCalls.push({ path: relative(repository, sourceFile.fileName), line: sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1, arguments: node.arguments.map(argument => ({ source: argument.getText(sourceFile).replace(/\s+/g, ' ').slice(0, 100), type: checker.typeToString(checker.getTypeAtLocation(argument)), family: primitiveFamily(checker.getTypeAtLocation(argument)) })) })
      }
      ts.forEachChild(node, visit)
    }
    visit(sourceFile)
  }
  for (const [node, info] of functions) {
    const { site } = details.get(node)
    if (info.maxControlDepth >= 4) site('deep-control-flow', node, `Maximum conditional/loop/try nesting is ${info.maxControlDepth}; nesting count alone does not establish a redundant branch.`)
    if (genericHelperName.test(info.name) && (info.typeChecks || info.catches || info.parameterTypes.some(parameter => parameter.broad))) {
      for (const [index, parameter] of info.parameterTypes.entries()) {
        const calls = info.directCalls.map(call => call.arguments[index])
        const families = calls.map(call => call?.family)
        const family = families[0]
        if (parameter.broad && calls.length && ['string', 'number', 'boolean'].includes(family) && families.every(item => item === family || item === 'absent')) site('overgeneric-internal-primitive-helper', node, { parameter: parameter.name, acceptedType: parameter.type, observedFamily: family, directCalls: info.directCalls, limitation: 'Direct callsite evidence only. Exports, callbacks, unchecked indexes, asserted external values and tests require manual contract review before narrowing.' })
      }
    }
  }
  return results
}
