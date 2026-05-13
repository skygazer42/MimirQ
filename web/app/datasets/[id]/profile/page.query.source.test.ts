import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset profile page query convergence', () => {
  it('uses TanStack Query for the initial dataset/profile/scan-runs bootstrap', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toContain('useQuery')
    expect(src).toContain('queryKey: datasetId ? queryKeys.datasets.detail(datasetId) : queryKeys.datasets.detail(')
    expect(src).toContain('queryKey: datasetId ? queryKeys.datasets.profileSummary(datasetId) : queryKeys.datasets.profileSummary(')
    expect(src).toContain("queryKeys.datasets.profileScanRuns(datasetId, { skip: 0, limit: 20 })")
    expect(src).toContain('const refreshProfileOverview = useCallback(async () => {')
    expect(src).not.toContain('const load = useCallback(async () => {')
    expect(src).not.toContain('detachPromise(load())')
    expect(src).not.toContain('setDataset(ds)')
    expect(src).not.toContain('setSummary(prof)')
    expect(src).not.toContain('setScanRuns(runList.items || [])')
  })

  it('uses infinite query for profile finding document lists', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('useInfiniteQuery')
    expect(src).toContain('queryKey: queryKeys.datasets.profileFindingDocuments(')
    expect(src).not.toContain('const [findingLoading, setFindingLoading]')
    expect(src).not.toContain('const [findingRes, setFindingRes]')
    expect(src).not.toContain('const loadMoreFinding = useCallback(async () => {')
    expect(src).not.toContain('setFindingRes({ total: res.total, items: [...findingRes.items, ...(res.items || [])] })')
  })

  it('uses infinite query for profile bucket document drilldowns', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('queryKey: queryKeys.datasets.profileBucketDocuments(')
    expect(src).not.toContain('const [bucketLoading, setBucketLoading]')
    expect(src).not.toContain('const [bucketRes, setBucketRes]')
    expect(src).not.toContain('const loadMoreBucket = useCallback(async () => {')
    expect(src).not.toContain('setBucketRes({ total: res.total, items: [...bucketRes.items, ...(res.items || [])] })')
  })
})
