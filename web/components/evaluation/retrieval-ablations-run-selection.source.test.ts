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
    expectSourceToContain(src, "import { settingsApi } from '@/lib/api/settings'")
    expectSourceToContain(src, 'queryKey: queryKeys.settings.snapshot')
    expectSourceToContain(src, 'setRerankerProvider(settingsSnapshot.rag.reranker_provider')
    expectSourceToContain(src, 'setRerankerTopN(settingsSnapshot.rag.reranker_top_n')
    expectSourceToContain(
      src,
      "queryKey: queryKeys.evaluations.list({ limit: 80, dataset_id: datasetId.trim() || undefined })"
    )
    expectSourceToContain(src, 'function AblationInfoTooltip')
    expectSourceToContain(src, 'label="查看运行记录选择说明"')
    expectSourceToContain(src, '当前数据集暂无可对比的运行记录')
    expectSourceToContain(src, '当前数据集只有 1 条运行记录')
    expectSourceToContain(src, '这里用于比较两次运行的配置、指标和逐样本差异')
    expectSourceToContain(src, 'disabled={diffLoading || !canGenerateDiff}')
    expectSourceToContain(src, '选择基线运行')
    expectSourceToContain(src, '选择候选运行')
    expectSourceToContain(src, 'RERANKER_PROVIDER_OPTIONS.map')
    expectSourceToContain(src, '<SelectValue placeholder="选择重排器" />')
    expectSourceNotToContain(src, 'setRerankerProvider(e.target.value)')
    expectSourceNotToContain(src, 'Diff Run')
    expectSourceNotToContain(src, '选择基线 Run')
    expectSourceNotToContain(src, '选择候选 Run')
    expectSourceNotToContain(src, 'border-amber-200 bg-amber-50 text-amber-700')
    expectSourceNotToContain(src, '选择 baseline')
    expectSourceNotToContain(src, '选择 candidate')
  })
})
