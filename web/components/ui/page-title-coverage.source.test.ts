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
    const chunkPreviewSrc = read('components/chunk-preview/components/workbench/index.tsx')
    const parsingSrc = read('components/parsing/parsing-workbench-shell.tsx')

    expect(knowledgeSrc).toContain('rounded-3xl border border-sky-200/60 bg-gradient-to-br from-white via-sky-50/40 to-blue-50/30')
    expect(knowledgeSrc).toContain('text-[26px] font-black tracking-tight text-slate-900')
    expect(ingestionSrc).toContain('Knowledge Ops')
    expect(ingestionSrc).toContain('文档资产治理中枢')
    expect(ingestionSrc).toContain('入库管理')
    expect(ingestionSrc).toContain('<PageTitleIcon name="ingestion-operation" className="size-9" />')
    expect(ingestionSrc).toContain('选择数据集与来源，先登记原始文件；解析、切块、建索引在后续流程手动控制。')
    expect(chunkPreviewSrc).toContain('KnowledgeOpsHero')
    expect(chunkPreviewSrc).toContain('文档资产治理中枢')
    expect(chunkPreviewSrc).toContain("title={t('workbench.title')}")
    expect(parsingSrc).toContain('KnowledgeOpsHero')
    expect(parsingSrc).toContain('文档资产治理中枢')
    expect(parsingSrc).toContain("title={t('title')}")
  })
})
