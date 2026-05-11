import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph scope picker dialog source', () => {
  it('loads dataset options through TanStack Query', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-scope-picker-dialog.tsx'), 'utf8')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toContain('useQuery')
    expect(src).toContain('queryKey: queryKeys.datasets.list')
    expect(src).toContain('enabled: open')
    expect(src).not.toContain('const [datasets, setDatasets]')
    expect(src).not.toContain('const [loading, setLoading]')
    expect(src).not.toContain('const [error, setError]')
    expect(src).not.toContain('const loadDatasets = useCallback')
    expect(src).not.toContain('void loadDatasets()')
  })
})
