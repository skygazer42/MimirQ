import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('TestCaseManager regression workspace density', () => {
  it('keeps the dense Golden evaluation set actionable when no cases exist', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'test-case-manager.tsx'), 'utf8')

    expect(src).toContain('暂无 Golden 评测样本')
    expect(src).toContain('为当前数据集添加标准问题、标准答案和标准证据')
    expect(src).toContain('Golden 评测集')
    expect(src).toContain('标准答案')
    expect(src).toContain('标准证据')
    expect(src).toContain('新增标准问答')
    expect(src).toContain('<Dialog open={isCreating} onOpenChange={setIsCreating}>')
    expect(src).toContain('<DialogTitle>新增标准问答</DialogTitle>')
    expect(src).toContain('导入 Evidence Pack')
    expect(src).toContain('运行 Golden')
    expect(src).toContain('运行全部')
    expect(src).toContain('REGRESSION_CASE_FETCH_MAX = 1000')
    expect(src).toContain('REGRESSION_CASE_PAGE_LIMIT = 200')
    expect(src).toContain('样本 {caseTotal}')
    expect(src).toContain('fullyLoaded: items.length >= total')
    expect(src).toContain('standardAnswerCount')
    expect(src).toContain('referenceSourceCount')
    expect(src).toContain('aria-label="Golden 评测集统计"')
    expect(src).toContain('filteredCases.length > 0 || selectedCaseIds.size > 0')
    expect(src).not.toContain('Golden {goldenCount} / 样本 {cases.length} · 标准答案 {standardAnswerCount} · 标准证据 {referenceSourceCount}')
    expect(src).not.toContain('共 {filteredCases.length} 个测试用例')
    expect(src).toContain('overflow-y-auto overscroll-contain custom-scrollbar')
    expect(src).not.toContain('flex-1 overflow-y-auto overscroll-contain no-scrollbar')
    expect(src).not.toContain('{isCreating && (')
    expect(src).toContain('STEP {step}')
    expect(src).toContain("placeholder=\"搜索问题、关键词或标签...\"")
    expect(src).toContain('...(Array.isArray(c.tags) ? c.tags : [])')
  })
})
