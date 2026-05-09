import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('retrieval ablations run selection', () => {
  it('loads runs by dataset and explains empty diff selection states', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieval-ablations-page.tsx'), 'utf8')

    expect(src).toContain('evaluationApi.listRegressionRuns({ limit: 80, dataset_id: ds || undefined })')
    expect(src).toContain('function AblationInfoTooltip')
    expect(src).toContain('label="查看 Diff Run 选择说明"')
    expect(src).toContain('当前数据集暂无可对比 run')
    expect(src).toContain('当前数据集只有 1 条 run')
    expect(src).toContain('这里用于比较两次运行的配置、指标和逐样本差异')
    expect(src).toContain('disabled={diffLoading || !canGenerateDiff}')
    expect(src).toContain('选择基线 run')
    expect(src).toContain('选择候选 run')
    expect(src).not.toContain('border-amber-200 bg-amber-50 text-amber-700')
    expect(src).not.toContain('选择 baseline')
    expect(src).not.toContain('选择 candidate')
  })
})
