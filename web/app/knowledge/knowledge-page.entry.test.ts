// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge route entry', () => {
  it('keeps app/knowledge/page.tsx as a thin wrapper (module boundary)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    expect(src).toContain("@/components/knowledge/knowledge-page")
  })

  it('preserves knowledge header context while its presentation is unified', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '../../components/knowledge/knowledge-page.tsx'),
      'utf8'
    )

    expect(src).toContain('data-knowledge-title-mark="true"')
    expect(src).toContain('src="/brand/mimirq-knowledge-mark.png"')
    expect(src).toContain('loading="eager"')
    expect(src).toContain('className="size-6 scale-110 object-contain"')
    expect(src).not.toContain('PageTitleIcon')
    expect(src).not.toContain('LibraryBig')
    expect(
      fs.existsSync(
        path.resolve(__dirname, '../../public/brand/mimirq-knowledge-mark.png')
      )
    ).toBe(true)
    expect(src).toContain("{t('header.title')}")
    expect(src).toContain("{t('header.description')}")
    expect(src).toContain("{selectedDatasetLabel || scopeT('dataset.all')}")
    expect(src).toContain('{activeTasksCount}')
    expect(src).toContain('采集')
    expect(src).toContain('资产')
    expect(src).toContain('验证')
    expect(src).toContain('data-testid="knowledge-page-toolbar"')
    expect(src).toContain('headerClassName="-mx-1 -mt-1 md:-mx-3 md:-mt-2"')
    expect(src).toContain('className="relative flex min-h-14 flex-col gap-2 border-b border-foreground/15 px-1 py-2 sm:flex-row sm:items-center sm:justify-between"')
    expect(src).toContain("const KNOWLEDGE_GLASS_CARD_CLASS =")
    expect(src).toContain('border-foreground/10 bg-background shadow-none backdrop-blur-none')
    expect(src).not.toContain('shadow-soft')
    expect(src).not.toContain('shadow-subtle')
    expect(src).not.toContain('Knowledge Ops')
    expect(src).not.toContain('文档资产治理中枢')
    expect(src).not.toContain('KNOWLEDGE_OPS_HERO_PANEL_CLASS')
    expect(src).not.toContain('KNOWLEDGE_OPS_SUMMARY_PANEL_CLASS')
  })

  it('keeps document metrics in actionable panels when duplicate summaries are removed', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, '../../components/knowledge/knowledge-page.tsx'),
      'utf8'
    )

    expect(src).toContain('totalDocs={totalDocs}')
    expect(src).toContain('completedDocsValue={completedDocsValue}')
    expect(src).toContain('processingDocsValue={processingDocsValue}')
    expect(src).toContain('failedDocsValue={failedDocsValue}')
    expect(src).toContain('quarantinedDocsValue={quarantinedDocsValue}')
    expect(src).toContain('aggregateDocuments={totalDocs}')
    expect(src).toContain('aggregateChunks={totalChunksValue}')
    expect(src).not.toContain('const settingsSummaryCards = useMemo(')
    expect(src).not.toContain('const summaryCards = useMemo(')
    expect(src).not.toContain('top={')
  })

  it('preserves scope and empty-shelf behavior while the workbench surface is unified', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, '../../components/knowledge/knowledge-page.tsx'),
      'utf8'
    )
    const documentsSrc = fs.readFileSync(
      path.resolve(__dirname, '../../components/knowledge/knowledge-documents-panel.tsx'),
      'utf8'
    )
    const scaffoldSrc = fs.readFileSync(
      path.resolve(__dirname, '../../components/workbench/workbench-scaffold.tsx'),
      'utf8'
    )

    expect(pageSrc).toContain('<KnowledgeScopePanel')
    expect(pageSrc).toContain('<KnowledgeDocumentsPanel')
    expect(documentsSrc).toContain('data-knowledge-empty-shelf="true"')
    expect(documentsSrc).toContain('data-knowledge-empty-shelf-dock="integrated-canvas"')
    expect(documentsSrc).toContain('data-knowledge-empty-shelf-mark="true"')
    expect(documentsSrc).toContain('aria-label="查看入库指引"')
    expect(documentsSrc).toContain('知识货架待入库')
    expect(documentsSrc).toContain('使用右上角「导入/新增」上传文档或创建连接器后')
    expect(documentsSrc).toContain('onClearFilters')
    expect(documentsSrc).toContain('onSwitchToAllDatasets')
    expect(pageSrc).toContain('paneGroupClassName={cn(')
    expect(documentsSrc).toContain('className="flex h-full min-h-0 flex-1"')
    expect(documentsSrc).toContain('className="relative flex h-full min-h-[360px] w-full flex-1 overflow-hidden')
    expect(documentsSrc).not.toContain('compactEmptyInventory')
    expect(documentsSrc).not.toContain('min-h-[clamp(220px,30vh,320px)]')
    expect(documentsSrc).toContain('导入文档')
    expect(documentsSrc).toContain('自动解析')
    expect(documentsSrc).toContain('建立索引')
    expect(documentsSrc).toContain('h-0.5 bg-border/80')
    expect(scaffoldSrc).toContain('paneGroupClassName?: string')
    expect(scaffoldSrc).toContain('data-workbench-pane-group="true"')
    expect(scaffoldSrc).toContain("className={cn('flex h-full min-h-0 gap-4', paneGroupClassName)}")
    expect(pageSrc).toContain("'gap-0 overflow-hidden rounded-lg border border-foreground/10 bg-background shadow-none dark:border-foreground/10 dark:bg-background'")
    expect(pageSrc).toContain("'flex h-full flex-col overflow-hidden rounded-none border-r border-y-0 border-l-0'")
    expect(pageSrc).toContain("'flex h-full flex-col overflow-hidden rounded-none border-l border-y-0 border-r-0'")
    expect(pageSrc).toContain("withDocumentViewerPadding={activeTab !== 'retrieval'}")
    expect(pageSrc).not.toContain('border-border/45 bg-background shadow-none')
  })

  it('preserves workbench actions while routine controls are visually flattened', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, '../../components/knowledge/knowledge-page.tsx'),
      'utf8'
    )

    expect(pageSrc).toContain("{ key: 'documents', label: t('tabs.documents.label'), icon: FileStack }")
    expect(pageSrc).toContain("{ key: 'retrieval', label: t('tabs.retrieval.label'), icon: Activity }")
    expect(pageSrc).toContain("{ key: 'settings', label: t('tabs.settings.label'), icon: Database }")
    expect(pageSrc).toContain('setActiveTab(tab.key)')
    expect(pageSrc).toContain('setDesktopScopeCollapsed((prev) => !prev)')
    expect(pageSrc).toContain('<KnowledgeWorkbenchActions')
    expect(pageSrc).toContain('onClick={() => detachPromise(loadDocuments())}')
    expect(pageSrc).toContain('documentScopeSummary')
    expect(pageSrc).toContain('toolbarClassName="px-3 py-2 md:px-3 md:py-2"')
    expect(pageSrc).toContain("'bg-foreground text-background shadow-none'")
    expect(pageSrc).toContain("'bg-background/35 px-3 pt-3 dark:bg-background/20 md:px-3'")
    expect(pageSrc).toContain('rounded-lg border border-foreground/10 bg-background/70')
    expect(pageSrc).toContain('border-foreground/10 bg-background shadow-none')
    expect(pageSrc).not.toContain('hover:shadow-md')
    expect(pageSrc).not.toContain('hover:bg-[linear-gradient(90deg')

    const documentsSrc = fs.readFileSync(
      path.resolve(__dirname, '../../components/knowledge/knowledge-documents-panel.tsx'),
      'utf8'
    )
    expect(documentsSrc).toContain('bg-[size:48px_48px] opacity-60')
    expect(documentsSrc).toContain('className="mb-4 flex size-12 items-center justify-center rounded-xl')
    expect(documentsSrc).not.toContain('radial-gradient(circle_at_50%_0%')
    expect(documentsSrc).not.toContain('文档货架\n')
    expect(documentsSrc).not.toContain('size-52 rounded-full bg-info/10 blur-3xl')
  })

  it('preserves settings scope, model selection, save and verification behavior', () => {
    const settingsSrc = fs.readFileSync(
      path.resolve(__dirname, '../../components/knowledge/knowledge-settings-panel.tsx'),
      'utf8'
    )

    expect(settingsSrc).toContain('value={selectedScopeValue}')
    expect(settingsSrc).toContain('onValueChange={onDatasetScopeChange}')
    expect(settingsSrc).toContain('EMBEDDING_PRESETS.map((preset) =>')
    expect(settingsSrc).toContain('await datasetApi.update(selectedDatasetId')
    expect(settingsSrc).toContain('await settingsApi.update(draftConfig)')
    expect(settingsSrc).toContain('await retrievalApi.configHash(hashRequest)')
    expect(settingsSrc).toContain('queryKeys.datasets.exhaustive()')
    expect(settingsSrc).toContain('onClick={handleSaveDraft}')
    expect(settingsSrc).toContain('onClick={handleApplyRecommendedConfig}')
    expect(settingsSrc).toContain('onGoToRetrievalTest?.()')
    expect(settingsSrc).toContain('setGuideExpanded')
    expect(settingsSrc).toContain('setCurrentConfigOpen')
    expect(settingsSrc).toContain("'rounded-xl border border-border/55 bg-background shadow-none backdrop-blur-none")
    expect(settingsSrc).toContain("'rounded-none border-0 border-b border-border/50 bg-transparent shadow-none backdrop-blur-none")
    expect(settingsSrc).toContain("'grid min-h-0 gap-0 lg:h-full'")
    expect(settingsSrc).toContain("'lg:grid-cols-[206px_minmax(0,1fr)]'")
    expect(settingsSrc).toContain('配置范围')
    expect(settingsSrc).toContain('当前自定义模型')
    expect(settingsSrc).toContain('hasCustomEmbeddingModel')
    expect(settingsSrc).toContain('useState(false)')
    expect(settingsSrc).toContain('className="grid gap-2 md:grid-cols-2"')
    expect(settingsSrc).toContain('xl:grid-cols-2')
    expect(settingsSrc).toContain('xl:col-span-2')
    expect(settingsSrc).toContain('shrink-0 whitespace-nowrap rounded-full')
    expect(settingsSrc).not.toContain('comparisonMetrics')
    expect(settingsSrc).not.toContain('当前配置预估效果')
    expect(settingsSrc).not.toContain('系统建议')
    expect(settingsSrc).not.toContain('bg-[linear-gradient(180deg')
    expect(settingsSrc).not.toContain('2xl:grid-cols-4')
    expect(settingsSrc).not.toContain('xl:grid-cols-[1fr_1fr_0.95fr]')
    expect(settingsSrc).not.toContain('>Navigation<')
  })
})
