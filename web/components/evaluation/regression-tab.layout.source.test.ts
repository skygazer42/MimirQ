import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('RegressionTestTab embedded layout', () => {
  it('keeps the regression workspace in a balanced three-column layout without duplicating dataset configuration', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'regression-tab.tsx'),
      'utf8'
    )
    const compactSrc = src.replace(/\s+/g, ' ')

    expect(src).toContain('xl:grid-cols-[320px_minmax(0,1fr)_300px]')
    expect(src).toContain('2xl:grid-cols-[330px_minmax(0,1fr)_310px]')
    expect(compactSrc).toContain(
      '先锁定数据集，再维护 Golden 评测集并运行当前 RAG pipeline。'
    )
    expect(src).toContain('Golden 评测集')
    expect(src).toContain('当前数据集的标准问答会作为固定标尺')
    expect(compactSrc).toContain(
      'max_cases: Math.min(Math.max(caseIds.length, 1), 500)'
    )
    expect(src).toContain('runs')
    expect(src).toContain('metrics')
    expect(src).toContain('标准答案对比')
    expect(src).toContain('标准证据命中')
    expect(src).toContain('业务元数据命中')
    expect(src).toContain('Run 对比结果')
    expect(src).toContain('差距分析就是把当前 RAG 的回答')
    expect(src).toContain('RegressionMetricCompactGrid')
    expect(src).not.toContain('<StatsGrid className="lg:grid-cols-3">')
    expect(src).not.toContain('const statusBadge')
    expect(src).not.toContain('{statusBadge}')
    expect(src).toContain('expected_metadata_hit_rate')
    expect(src).toContain('expected_metadata_recall')
    expect(src).toContain('expected_metadata_fields_matched')
    expect(src).toContain('expected_metadata_missing_keys')
    expect(src).not.toContain('source_record_id、chunk_kind')
    expect(src).toContain('缺失字段')
    expect(src).toContain('summary.multimodal_slices')
    expect(src).toContain('multimodalTextOnlyFullCoverage')
    expect(src).toContain('shouldShowMultimodalSlicePanel')
    expect(src).toContain('label="切片覆盖"')
    expect(src).toContain('切片覆盖异常')
    expect(src).toContain('纯文本 100% 会收进上方摘要')
    expect(src).not.toContain('多模态切片')
    expect(src).toContain('Chart')
    expect(src).toContain('Formula')
    expect(src).toContain('Table-Math')
    expect(src).toMatch(/key=\{metric\.key\}\s+compact/)
    expect(src).toContain('summary="评分维度"')
    expect(src).toContain('默认收起，展开后选择 RAGAS 与程序化指标。')
    expect(src).toContain('p-2.5 pb-6 custom-scrollbar')
    expect(src).toContain('min-h-0 flex-1 grid p-0')
    expect(src).toContain(
      'overflow-y-auto overscroll-contain pr-1 custom-scrollbar'
    )
    expect(src).toContain('overflow-y-auto overscroll-contain custom-scrollbar')
    expect(src).toContain('RegressionMetricGuideCard')
    expect(src).toContain('评测维度速览')
    expect(src).toContain('查看全部历史')
    expect(src).toContain('min-h-[128px]')
    expect(src).toContain('min-h-[180px]')
    expect(src).toContain('px-3 py-5 text-center')
    expect(src).not.toContain('px-4 py-8 text-center')
    expect(src).not.toContain('min-h-[260px]')
    expect(src).not.toContain('p-2.5 pb-20 no-scrollbar')
    expect(src).not.toContain('embedded && "overflow-visible"')
    expect(src).not.toContain(
      'title="数据集"\\n                  description="回归 case 和 runs 都是数据集作用域'
    )
  })
})
