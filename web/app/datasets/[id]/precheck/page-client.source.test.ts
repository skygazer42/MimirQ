import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset precheck page client source', () => {
  it('loads dataset metadata and precheck run list through TanStack Query', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toContain('useQuery')
    expect(src).toContain('queryKey: queryKeys.datasets.detail')
    expect(src).toContain('queryKey: queryKeys.datasets.precheckRuns')
    expect(src).toContain('refreshPrecheckPage')
    expect(src).toContain('refreshPrecheckRuns')
    expect(src).not.toContain('const [dataset, setDataset]')
    expect(src).not.toContain('const [runs, setRuns]')
    expect(src).not.toContain('const [loading, setLoading]')
    expect(src).not.toContain('const load = useCallback')
    expect(src).not.toContain('const loadRuns = useCallback')
    expect(src).not.toContain('detachPromise(load())')
  })

  it('uses on-demand TanStack Query for samples, near-dup, and diff buttons', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('queryKey: queryKeys.datasets.precheckSamples(')
    expect(src).toContain('queryKey: queryKeys.datasets.precheckNearDups(')
    expect(src).toContain('queryKey: queryKeys.datasets.precheckDiff(')
    expect(src).not.toContain('const loadSamples = useCallback(async () => {')
    expect(src).not.toContain('const loadNearDups = useCallback(async () => {')
    expect(src).not.toContain('const loadDiff = useCallback(async () => {')
    expect(src).not.toContain('detachPromise(loadSamples())')
    expect(src).not.toContain('detachPromise(loadNearDups())')
    expect(src).not.toContain('detachPromise(loadDiff())')
  })

  it('uses on-demand TanStack Query for ingestion policy suggestions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('queryKey: queryKeys.datasets.precheckIngestionPolicySuggestion(')
    expect(src).not.toContain('const [policyLoading, setPolicyLoading]')
    expect(src).not.toContain('const [policyRes, setPolicyRes]')
    expect(src).not.toContain('setPolicyLoading(true)')
    expect(src).not.toContain('setPolicyRes(res)')
  })

  it('uses infinite query for precheck finding file lists', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('useInfiniteQuery')
    expect(src).toContain('queryKey: queryKeys.datasets.precheckFindingFiles(')
    expect(src).not.toContain('const [findingLoading, setFindingLoading]')
    expect(src).not.toContain('const [findingRes, setFindingRes]')
    expect(src).not.toContain('const loadMoreFinding = useCallback(async () => {')
    expect(src).not.toContain('setFindingRes({ total: res.total, items: [...findingRes.items, ...(res.items || [])] })')
  })
})
