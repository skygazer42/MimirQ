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

    expect(src).toContain('DashboardStatCard')
    expect(src).toContain('text-[20px] font-semibold')
    expect(src).not.toContain('text-[24px] font-semibold ')
    expect(src).toContain('min-h-[62px] rounded-xl')
    expect(src).toContain('text-[14px] font-semibold')
    expect(src).toContain('valueClassName="text-[13.5px] font-medium"')
    expect(src).toContain('实时会话')
    expect(src).toContain('平均开销')
    expect(src).toContain('运行详情')
    expect(src).toContain('评分明细')
    expect(src).toContain('逐轮明细')
    expect(src).toContain('density="compact"')
    expect(src).toContain('min-h-[148px]')
    expect(src).toContain('max-h-[276px]')
    expect(src).toContain('RunRecordCard')
    expect(src).toContain('isRunRecordsCollapsed')
    expect(src).toContain('id="ragas-run-records-list"')
    expect(src).toContain('max-h-[560px] min-h-0 space-y-1.5 overflow-y-auto')
    expect(src).toContain('xl:grid-cols-[260px_minmax(0,1fr)_270px]')
    expect(src).toContain('shrink-0 whitespace-nowrap')
    expect(src).toContain(
      'flex h-[calc(100vh-255px)] min-h-[610px] flex-col overflow-hidden'
    )
    expect(src).toContain('displayMetrics.length ? null')
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
