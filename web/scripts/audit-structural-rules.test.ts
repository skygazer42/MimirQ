import path from 'node:path'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

import { buildStructuralReviews, collectPureReturnLadderEdits } from './audit-structural-rules.mjs'

function review(text: string) {
  const filename = path.resolve('structural-rule-fixture.ts')
  const source = ts.createSourceFile(filename, text, ts.ScriptTarget.Latest, true)
  const host = ts.createCompilerHost({ strict: true, noEmit: true })
  const originalGetSourceFile = host.getSourceFile.bind(host)
  host.getSourceFile = (name, ...args) => path.resolve(name) === filename ? source : originalGetSourceFile(name, ...args)
  const program = ts.createProgram([filename], { strict: true, noEmit: true, types: [] }, host)
  return buildStructuralReviews([program.getSourceFile(filename)!], program.getTypeChecker(), process.cwd()).get('structural-rule-fixture.ts')!
}

describe('structural audit boundary evidence', () => {
  it('finds a broad numeric adapter while retaining unknown external call evidence', () => {
    const report = review('function safeNumber(value: unknown) { return Number(value) } function normalizeExternal(value: unknown) { return Number(value) } safeNumber(4); const raw: unknown = {}; normalizeExternal(raw);')

    const candidates = report.candidates.filter((candidate: { kind: string }) => candidate.kind === 'overgeneric-internal-primitive-helper')
    expect(candidates).toHaveLength(1)
    expect(candidates[0].source).toContain('safeNumber')
    expect(candidates[0].evidence.directCalls[0].arguments[0].family).toBe('number')
  })

  it('detects return scaffolding without rewriting or conflating nested callback scopes', () => {
    const code = 'const label = (() => { if (true) { return "yes" } else { return "no" } })();'
    const report = review(code)

    expect(report.candidates.map((candidate: { kind: string }) => candidate.kind)).toEqual(expect.arrayContaining(['immediate-function-wrapper', 'else-after-terminal-branch']))
    expect(report.functions).toHaveLength(1)
    expect(report.functions[0].maxControlDepth).toBe(1)
  })

  it('flattens exit-only branches and preserves branches with block-local declarations', () => {
    const code = 'function label(n: number) { if (n === 1) { return "one" } else if (n === 2) { return "two" } else { return "other" } } function scoped(flag: boolean) { if (flag) { return 1 } else { const local = 2; return local } }'
    const source = ts.createSourceFile('fixture.ts', code, ts.ScriptTarget.Latest, true)
    const edits = collectPureReturnLadderEdits(source)

    expect(edits).toHaveLength(1)
    const edit = edits[0]
    const result = code.slice(0, edit.start) + edit.replacement + code.slice(edit.end)
    expect(result).not.toContain('else if')
    expect(result).toContain('else { const local = 2; return local }')
    const javascript = ts.transpileModule(result + '; export { label };', { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
    const exported = {} as { label: (value: number) => string }
    Function('exports', javascript)(exported)
    expect([1, 2, 3].map(exported.label)).toEqual(['one', 'two', 'other'])
  })
})
