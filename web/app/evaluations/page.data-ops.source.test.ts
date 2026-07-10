import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('evaluations page data operations', () => {
  it('keeps advanced data operations off the main evaluation workspace', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).not.toContain(
      "import { EvaluationDataOpsPanel } from '@/components/evaluation/evaluation-data-ops-panel'"
    )
    expect(src).not.toContain('<EvaluationDataOpsPanel')
    expect(src).not.toContain('高级数据运维')
    expect(src).not.toContain('默认收起，仅用于导入、导出、清理与 KG 诊断')
  })

  it('keeps the conversation evaluation workspace aligned with the dashboard design', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('EvaluationHeroCard')
    expect(src).toContain('showAblationsEntry')
    expect(src).toContain("canShowAdminControlledNavigationModule(tenantAccess.data, 'ablations')")
    expect(src).toContain('href="/evaluations/ablations"')
    expect(src).toContain('检索调参对比')
    expect(src).toContain('EvaluationResultsStage')
    expect(src).toContain('EvaluationStageStat')
    expect(src).toContain('buildEvidenceReadinessState')
    expect(src).toContain('description={activeTabMeta.description}')
    expect(src).toContain('className="sr-only"')
    expect(src).toContain('rounded-2xl border border-sky-100/50 bg-white/80 shadow-md backdrop-blur-sm')
    expect(src).toContain('实时会话')
    expect(src).toContain('运行详情')
    expect(src).toContain('得分概览')
    expect(src).toContain('评分明细')
    expect(src).toContain('逐轮明细')
    expect(src).toContain('density="compact"')
    expect(src).toContain('min-h-[148px]')
    expect(src).toContain('max-h-[276px]')
    expect(src).toContain('RunRecordCard')
    expect(src).toContain('CollapsedWorkspaceRail')
    expect(src).toContain('setupRailCollapsed')
    expect(src).toContain('runsRailCollapsed')
    expect(src).toContain('收起参数栏')
    expect(src).toContain('收起运行记录侧栏')
    expect(src).toContain("side === 'left' ? `展开${title}` : `展开${title}侧栏`")
    expect(src).toContain('isRunRecordsCollapsed')
    expect(src).toContain('id="ragas-run-records-list"')
    expect(src).toContain('max-h-[560px] min-h-0 space-y-2 overflow-y-auto overscroll-contain pr-1 no-scrollbar')
    expect(src).toContain('xl:grid-cols-[280px_minmax(0,1fr)_280px]')
    expect(src).toContain('xl:grid-cols-[56px_minmax(0,1fr)_56px]')
    expect(src).toContain('shrink-0 whitespace-nowrap')
    expect(src).toContain(
      'flex h-[calc(100vh-255px)] min-h-[610px] flex-col overflow-hidden'
    )
    expect(src).toContain('showBreakdownPanels')
    expect(src).toContain('fillAvailableHeight={!showBreakdownPanels}')
    expect(src).toContain('flex min-h-0 min-w-0 flex-col gap-3')
    expect(src).toContain('刷新')
    expect(src).toContain('已收起 {runs.length}')
    expect(src).toContain('xl:grid-cols-[0.85fr_1.25fr]')
    expect(src).not.toContain('EvaluationOverviewMetric')
    expect(src).not.toContain('overviewMetrics')
    expect(src).not.toContain('grid divide-y divide-sky-100/50 sm:grid-cols-2 sm:divide-x sm:divide-y-0 xl:grid-cols-5')
    expect(src).not.toContain('conversationLayoutColumns')
    expect(src).not.toContain('isSetupPanelCollapsed')
    expect(src).not.toContain('visibleRunLimit')
    expect(src).not.toContain('加载更多')
    expect(src).not.toContain('<div className="px-4 py-8">')
    expect(src).not.toContain('<div className="px-4 py-10">')
  })

  it('positions regression as dataset-scoped Golden RAG evaluation', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('function parseEvaluationTab')
    expect(src).toMatch(
      /useState<TabType>\(\s*\(\) => parseEvaluationTab\(searchParams\.get\('tab'\)\) \|\| 'conversation'\s*\)/
    )
    expect(src).toContain("label: 'Golden 评测集'")
    expect(src).toContain("title: 'Golden 回归评测'")
    expect(src).toContain(
      '用数据集级标准问答和标准证据持续评估当前 RAG pipeline。'
    )
  })
})
