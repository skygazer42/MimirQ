import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('datasets-page server pagination contract', () => {
  it('uses the paginated dataset list query instead of exhaustive client filtering', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'datasets-page.tsx'), 'utf8')

    expect(src).toContain('const DATASET_SEARCH_DEBOUNCE_MS = 220')
    expect(src).toContain("const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('')")
    expect(src).toContain('setDebouncedSearchQuery(trimmedSearchQuery)')
    expect(src).toContain('}, DATASET_SEARCH_DEBOUNCE_MS)')
    expect(src).toContain('maxLength={DATASET_SEARCH_MAX_LENGTH}')
    expect(src).toContain('buildDatasetListParams({')
    expect(src).toContain('searchQuery: debouncedSearchQuery')
    expect(src).toContain('queryKeys.datasets.list(datasetListParams)')
    expect(src).toContain('queryFn: () => datasetApi.list(datasetListParams)')
    expect(src).toContain('operational_status: input.collectionFilter')
    expect(src).toContain("order_by: input.sortBy === 'name_asc' ? 'name' : 'created_at'")
    expect(src).toContain("order_dir: input.sortBy === 'name_asc' ? 'asc' : 'desc'")
    expect(src).toContain('const scopeTotal = response?.facets?.scope_total ?? 0')
    expect(src).toContain('const filteredTotal = response?.facets?.filtered_total ?? 0')
    expect(src).not.toContain('datasetApi.listAll(datasetListParams)')
    expect(src).not.toContain('datasetApi.getIngestionStats(')
  })
})

describe('datasets-page header action contract', () => {
  it('keeps refresh and create actions wired while the header is simplified', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'datasets-page.tsx'), 'utf8')

    expect(src).toMatch(/onClick=\{\(\) => \{\s*detachPromise\(refreshDatasets\(\)\)\s*\}\}/)
    expect(src).toContain('disabled={isRefreshing}')
    expect(src).toMatch(
      /<Dialog\s+open=\{createOpen\}\s+onOpenChange=\{\(open\) => \{\s*setCreateOpen\(open\);?\s*if \(open\) resetForm\(\)\s*\}\}\s*>/,
    )
    expect(src).toContain('<DialogTrigger asChild>')
    expect(src).toContain('<CreateDatasetButton')
    expect(src).toMatch(/<Button onClick=\{handleCreate\} disabled=\{!canSubmit\}>\s*确认创建\s*<\/Button>/)
  })
})
