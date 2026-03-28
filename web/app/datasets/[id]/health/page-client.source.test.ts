import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset health page client source', () => {
  it('uses React Query for dataset and health loading', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toContain('const datasetQuery = useQuery({')
    expect(src).toContain('const healthQuery = useQuery({')
    expect(src).toContain('queryKey: queryKeys.datasets.detail(datasetId)')
    expect(src).toContain('queryKey: queryKeys.datasets.health(datasetId)')
    expect(src).toContain('enabled: Boolean(datasetId)')
    expect(src).toContain('datasetQuery.refetch()')
    expect(src).toContain('healthQuery.refetch()')
  })
})
