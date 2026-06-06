import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('regression tab query convergence', () => {
  it('uses TanStack Query for regression run list and detail polling', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'regression-tab.tsx'),
      'utf8'
    )

    expect(src).toContain("import { useQuery } from '@tanstack/react-query'")
    expect(src).toContain(
      'queryKey: queryKeys.evaluations.regressionRuns({ limit: 50 })'
    )
    expect(src).toContain(
      'queryKey: queryKeys.evaluations.regressionRunDetail(selectedRunId, {'
    )
    expect(src).toContain("const deepLinkDatasetId = searchParams.get('dataset_id') || ''")
    expect(src).toContain("const deepLinkRunId = searchParams.get('run_id') || ''")
    expect(src).toContain('setSelectedDatasetId(deepLinkDatasetId)')
    expect(src).toContain('setSelectedRunId(deepLinkRunId)')
    expect(src).toContain('selectedRunId === deepLinkRunId')
    expect(src).toContain('refetchInterval: (query) => {')
    expect(src).not.toContain('const loadRuns = useCallback(async () => {')
    expect(src).not.toContain('detachPromise(loadRuns())')
    expect(src).not.toContain('const fetchDetail = async () => {')
    expect(src).not.toContain('timer = setTimeout(fetchDetail, 2000)')
  })
})
