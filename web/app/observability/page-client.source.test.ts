import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('observability page client source', () => {
  it('uses React Query for summary and analytics loading', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toContain("queryKey: ['observability', 'summary', windowMinutes]")
    expect(src).toContain("queryKey: ['observability', 'query_analytics', windowMinutes, slowThresholdSec]")
    expect(src).toContain("enabled: tab === 'summary'")
    expect(src).toContain("enabled: tab === 'query_analytics'")
    expect(src).toContain('placeholderData: keepPreviousData')
    expect(src).toContain('summaryQuery.refetch()')
    expect(src).toContain('analyticsQuery.refetch()')
  })
})
