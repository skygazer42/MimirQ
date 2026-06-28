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

  it('app/reports/page-client.tsx renders the shared analysis page shell', () => {
    const src = read('app/reports/page-client.tsx')

    expect(src).toContain('AnalysisPageShell')
    expect(src).toContain('<AnalysisPageShell')
  })

  it('keeps graph canvas title visually aligned without using the full page header layout', () => {
    const src = read('app/graph/_components/graph-page-header.tsx')

    expect(src).toContain('bg-[linear-gradient(135deg,hsl(var(--card)/0.98),hsl(var(--muted)/0.34))]')
    expect(src).toContain('bg-[linear-gradient(90deg,hsl(var(--foreground)),hsl(var(--info))_92%)] bg-clip-text text-transparent')
    expect(src).toContain('<PageTitleIcon name="knowledge-graph" className="size-7" />')
  })

  it('styles custom dense workbench titles that cannot use the full shared header', () => {
    const knowledgeSrc = read('components/knowledge/knowledge-page.tsx')
    const ingestionSrc = read('app/knowledge/ingestion/operation-page-client.tsx')

    expect(knowledgeSrc).toContain('bg-[linear-gradient(90deg,hsl(var(--foreground)),hsl(var(--info))_92%)] bg-clip-text text-transparent')
    expect(ingestionSrc).toContain('入库中心')
    expect(ingestionSrc).toContain('<PageHeader')
    expect(ingestionSrc).toContain('iconImage="ingestion-operation"')
    expect(ingestionSrc).toContain('选择数据集与来源，先登记原始文件；解析、切块、建索引在后续流程手动控制。')
  })
})
