import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset precheck page client source', () => {
  it('loads dataset metadata and precheck run list through TanStack Query', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toContain('useQuery')
    expect(src).toContain('queryKey: queryKeys.datasets.detail')
    expect(src).toContain("queryKey: queryKeys.datasets.precheckRuns(datasetId || '', PRECHECK_RUNS_PARAMS)")
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

  it('renders a clear empty state before any precheck scan exists', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('const hasPrecheckRuns = runs.length > 0')
    expect(src).toContain('const showPrecheckEmptyState = !loading && !hasPrecheckRuns')
    expect(src).toContain('hidden={showPrecheckEmptyState}')
    expect(src).toContain('等待第一次扫描')
    expect(src).toContain('文档入库 / 切片 / 索引 / KG')
  })

  it('keeps dense page actions in the toolbar so they do not crush the title', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('toolbar={')
    expect(src).not.toContain('actions={')
  })

  it('matches the precheck control-room layout from the design mock', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('precheckHeroCard')
    expect(src).toContain('数据源')
    expect(src).toContain('查看数据集')
    expect(src).toContain('查看历史记录')
    expect(src).toContain('扫描配置')
    expect(src).toContain('RUN STATE')
    expect(src).toContain('尚未运行扫描，以上信息将在执行后更新。')
    expect(src).toContain('预估样本量')
    expect(src).toContain('输出类型')
  })

  it('uses dense workbench copy for the precheck configuration panel', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('文件摸底 / 质量画像 / 不入库不切片')
    expect(src).toContain('扫描配置')
    expect(src).toContain('grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_420px]')
    expect(src).toContain('RUN STATE')
  })
})
