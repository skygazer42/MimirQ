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
})
