import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('datasets-page server pagination contract', () => {
  it('uses the paginated dataset list query instead of exhaustive client filtering', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'datasets-page.tsx'), 'utf8')

    expect(src).toContain('const DATASET_SEARCH_DEBOUNCE_MS = 220')
    expect(src).toContain('const [debouncedSearchQuery, setDebouncedSearchQuery] = useState(\'\')')
    expect(src).toContain('setDebouncedSearchQuery(trimmedSearchQuery)')
    expect(src).toContain('}, DATASET_SEARCH_DEBOUNCE_MS)')
    expect(src).toContain('maxLength={DATASET_SEARCH_MAX_LENGTH}')
    expect(src).toContain('buildDatasetListParams({')
    expect(src).toContain('searchQuery: debouncedSearchQuery')
    expect(src).toContain('queryKeys.datasets.list(datasetListParams)')
    expect(src).toContain('queryFn: () => datasetApi.list(datasetListParams)')
    expect(src).toContain("operational_status: input.collectionFilter")
    expect(src).toContain("order_by: input.sortBy === 'name_asc' ? 'name' : 'created_at'")
    expect(src).toContain("order_dir: input.sortBy === 'name_asc' ? 'asc' : 'desc'")
    expect(src).toContain('const scopeTotal = Number(response?.facets?.scope_total || 0)')
    expect(src).toContain('const filteredTotal = Number(response?.facets?.filtered_total || 0)')
    expect(src).not.toContain('datasetApi.listAll(datasetListParams)')
    expect(src).not.toContain('datasetApi.getIngestionStats(')
  })
})

describe('datasets-page header action contract', () => {
  it('keeps refresh and create actions wired while the header is simplified', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'datasets-page.tsx'), 'utf8')

    expect(src).toContain('onClick={() => { detachPromise(refreshDatasets()) }}')
    expect(src).toContain('disabled={isRefreshing}')
    expect(src).toContain('<Dialog open={createOpen} onOpenChange={(open) => { setCreateOpen(open); if (open) resetForm() }}>')
    expect(src).toContain('<DialogTrigger asChild>')
    expect(src).toContain('<CreateDatasetButton')
    expect(src).toContain('<Button onClick={handleCreate} disabled={!canSubmit}>确认创建</Button>')
  })

  it('uses a compact management toolbar without decorative workflow chrome', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'datasets-page.tsx'), 'utf8')

    expect(src).toContain('data-testid="datasets-page-toolbar"')
    expect(src).toContain('bodyGutter="none"')
    expect(src).toContain('bodyClassName="bg-sidebar/20 px-3 pt-0 pb-3"')
    expect(src).toContain('topClassName="bg-sidebar/20 px-3 pt-2 pb-2 md:px-3 lg:px-3"')
    expect(src).toContain('className="relative flex min-h-14 flex-col gap-2 border-b border-foreground/15 px-1 py-2 sm:flex-row sm:items-center sm:justify-between"')
    expect(src).toContain('left-1 h-px w-8 bg-info/55')
    expect(src).toContain('<h1 className="text-[19px] font-semibold leading-6 tracking-[-0.02em] text-foreground">数据集</h1>')
    expect(src).toContain('<p className="truncate text-[12px] leading-5 text-muted-foreground/80">管理知识库集合与访问权限</p>')
    expect(src).toContain('DialogContent className="max-w-xl p-0 sm:rounded-xl"')
    expect(src).not.toContain('rounded-xl border border-border/60 bg-background/88')
    expect(src).not.toContain('Dataset Ops')
    expect(src).not.toContain('权限与资产编排')
    expect(src).not.toContain('KNOWLEDGE_OPS_HERO_PANEL_CLASS')
    expect(src).not.toContain('PageTitleIcon')
  })
})

describe('datasets-page workspace behavior contract', () => {
  it('preserves catalog controls and selected-dataset operations during visual cleanup', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'datasets-page.tsx'), 'utf8')

    expect(src).toContain('value={searchQuery}')
    expect(src).toContain('onChange={(e) => setSearchQuery(e.target.value)}')
    expect(src).toContain('<Select value={sortBy} onValueChange={(value) => setSortBy(value as \'default\' | \'name_asc\')}>')
    expect(src).toContain("setSearchQuery('')")
    expect(src).toContain("setCollectionFilter('all')")
    expect(src).toContain('setSelectedCategoryId(null)')
    expect(src).toContain('onClick={() => setSelectedDatasetId(dataset.id)}')
    expect(src).toContain('handleInspectorPermissionChange(selectedDataset, value as PermissionEnum)')
    expect(src).toContain('handleToggleDefaultPipeline(selectedDataset, nextChecked)')
    expect(src).toContain('openEdit(selectedDataset)')
    expect(src).toContain('setDeleteTarget(selectedDataset)')
  })

  it('uses a flat selection-driven workspace without duplicate metric cards', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'datasets-page.tsx'), 'utf8')

    expect(src).toContain('data-testid="datasets-workspace"')
    expect(src).toContain("'grid min-h-0 flex-1 bg-sidebar/22 lg:grid-cols-[216px_minmax(0,1fr)]'")
    expect(src).toContain('rounded-lg border border-foreground/15 bg-sidebar/18')
    expect(src).toContain('border-foreground/10 bg-sidebar/28 p-3')
    expect(src).toContain("'border-foreground/10 bg-info/[0.04] ring-1 ring-info/15'")
    expect(src).toContain("'border-foreground/10 bg-info/[0.06] text-info shadow-none'")
    expect(src).toContain('w-fit shrink-0 justify-self-start items-center gap-1 rounded-md border border-foreground/10 bg-background/70')
    expect(src).toContain('data-testid="dataset-inspector"')
    expect(src).toMatch(/\{selectedDataset \? \(\s*<aside\s+data-testid="dataset-inspector"/)
    expect(src).toContain('aria-label="搜索数据集"')
    expect(src).toContain('className="min-h-full rounded-none border-0 bg-transparent shadow-none"')
    expect(src).toContain('rounded-lg border border-foreground/10 bg-background/70')
    expect(src).not.toContain('rounded-[20px]')
    expect(src).not.toContain('backdrop-blur')
    expect(src).not.toContain('shadow-[0_14px_26px_-22px_hsl(var(--info)/0.22)]')
    expect(src).not.toContain('function DatasetSummaryCard')
    expect(src).not.toContain('<DatasetSummaryCard')
    expect(src).not.toContain('检视器就绪')
    expect(src).not.toContain('Dataset Catalog')
    expect(src).not.toContain('Dataset Inspector')
    expect(src).not.toContain('AnimatePresence')
  })

  it('keeps operational controls but removes decorative floating chrome from dataset actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'datasets-page.tsx'), 'utf8')

    expect(src).toContain('className="focus-ring group relative flex min-h-[70px] flex-col items-start justify-between rounded-lg border border-foreground/10 bg-background/70 px-2 py-1.5 transition-colors duration-200 hover:border-foreground/15 hover:bg-muted/20 active:scale-[0.98]"')
    expect(src).toContain('className="focus-ring group relative flex min-h-[38px] items-center gap-1.5 rounded-md border border-foreground/10 bg-background/70 px-2 py-1.5 transition-colors duration-200 hover:border-foreground/15 hover:bg-muted/20 active:scale-[0.98]"')
    expect(src).toContain('className="rounded-md border border-foreground/10 bg-background/70 px-2 py-1.5 transition-colors duration-200 hover:border-foreground/15 hover:bg-background"')
    expect(src).not.toContain('backdrop-blur transition-all duration-200 group-hover:translate-y-0 group-hover:opacity-100')
    expect(src).not.toContain('hover:shadow-[0_12px_22px_-18px_rgba(15,23,42,0.14)]')
    expect(src).not.toContain('hover:-translate-y-0.5')
  })
})
