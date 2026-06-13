import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('retrieval ablations query convergence', () => {
  it('uses TanStack Query for dataset and run list loading', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'retrieval-ablations-page.tsx'),
      'utf8'
    )

    expect(src).toContain("import { useQuery } from '@tanstack/react-query'")
    expect(src).toContain('queryKey: queryKeys.datasets.list(RETRIEVAL_ABLATION_DATASET_PARAMS)')
    expect(src).toContain("queryKey: queryKeys.evaluations.list({ limit: 80, dataset_id: datasetId.trim() || undefined })")
    expect(src).toContain('queryKey: queryKeys.evaluations.regressionCases({')
    expect(src).toContain('evaluationApi.listRegressionCases({')
    expect(src).toContain('当前数据集没有 Golden/Regression 样本')
    expect(src).not.toContain('const loadDatasets = useCallback(async (): Promise<void> => {')
    expect(src).not.toContain('const refreshRuns = useCallback(async (): Promise<void> => {')
    expect(src).not.toContain('detachPromise(loadDatasets())')
    expect(src).not.toContain('detachPromise(refreshRuns())')
  })
})
