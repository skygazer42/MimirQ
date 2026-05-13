import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const repoRoot = path.resolve(__dirname, '../..')

function read(relativePath: string) {
  return fs.readFileSync(path.join(repoRoot, relativePath), 'utf8')
}

describe('navigation page title coverage', () => {
  it.each([
    ['app/diagnostics/page-client.tsx'],
    ['app/evaluations/page.tsx'],
    ['app/prompts/page.tsx'],
    ['app/reports/page-client.tsx'],
    ['components/chunk-preview/components/workbench/index.tsx'],
    ['components/evaluation/retrieval-ablations-page.tsx'],
    ['components/graph/kg-diagnostics-page.tsx'],
    ['components/graph/kg-snapshots-page.tsx'],
    ['components/ragviz/similarity-workbench.tsx'],
  ])('%s renders the shared page title shell', (relativePath) => {
    const src = read(relativePath)

    expect(src).toContain('PageHeader')
    expect(src).toContain('<PageHeader')
  })

  it('keeps graph canvas title visually aligned without using the full page header layout', () => {
    const src = read('app/graph/_components/graph-page-header.tsx')

    expect(src).toContain('bg-[linear-gradient(135deg,hsl(var(--card)/0.98),hsl(var(--muted)/0.34))]')
    expect(src).toContain('bg-[linear-gradient(90deg,hsl(var(--foreground)),hsl(var(--info))_92%)] bg-clip-text text-transparent')
    expect(src).toContain('<Network className="size-[18px]"')
  })

  it('styles custom dense workbench titles that cannot use the full shared header', () => {
    const knowledgeSrc = read('components/knowledge/knowledge-page.tsx')
    const ingestionSrc = read('app/knowledge/ingestion/page-client.tsx')

    expect(knowledgeSrc).toContain('bg-[linear-gradient(90deg,hsl(var(--foreground)),hsl(var(--info))_92%)] bg-clip-text text-transparent')
    expect(ingestionSrc).toContain('bg-[linear-gradient(135deg,hsl(var(--background)/0.92),hsl(var(--muted)/0.36))]')
    expect(ingestionSrc).toContain('售前报价证据台')
    expect(ingestionSrc).toContain('执行监控工作台')
  })
})
