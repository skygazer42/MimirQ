import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const sourcePath = path.resolve(__dirname, 'datasets-page.tsx')

describe('datasets page ingestion stats loading', () => {
  it('loads stats only for the visible page and avoids unbounded fan-out', () => {
    const src = fs.readFileSync(sourcePath, 'utf8')

    expect(src).toContain('const DATASET_STATS_REQUEST_SPACING_MS =')
    expect(src).toContain('const requestedStatsIdsRef = useRef<Set<string>>(new Set())')
    expect(src).toContain('const missingIds = pagedItems')
    expect(src).toContain('requestedStatsIdsRef.current.has(id)')
    expect(src).toContain('for (const datasetId of missingIds)')
    expect(src).not.toContain('const missingIds = items')
    expect(src).not.toContain('Promise.all(')
  })
})
