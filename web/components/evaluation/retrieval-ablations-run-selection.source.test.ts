import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('retrieval ablations run selection', () => {
  it('loads runs by dataset and explains empty diff selection states', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'retrieval-ablations-page.tsx'),
      'utf8'
    )

    expectSourceToContain(src, "import { useQuery } from '@tanstack/react-query'")
    expectSourceToContain(
      src,
      "queryKey: queryKeys.evaluations.list({ limit: 80, dataset_id: datasetId.trim() || undefined })"
    )
    expectSourceToContain(src, 'function AblationInfoTooltip')
    expectSourceToContain(src, 'label="查看 Diff Run 选择说明"')
    expectSourceToContain(src, '当前数据集暂无可对比 run')
    expectSourceToContain(src, '当前数据集只有 1 条 run')
    expectSourceToContain(src, '这里用于比较两次运行的配置、指标和逐样本差异')
    expectSourceToContain(src, 'disabled={diffLoading || !canGenerateDiff}')
    expectSourceToContain(src, '选择基线 run')
    expectSourceToContain(src, '选择候选 run')
    expectSourceNotToContain(src, 'border-amber-200 bg-amber-50 text-amber-700')
    expectSourceNotToContain(src, '选择 baseline')
    expectSourceNotToContain(src, '选择 candidate')
  })
})
