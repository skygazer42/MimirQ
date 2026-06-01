'use client'

import type { ChangeEventHandler, ReactNode, RefObject } from 'react'

import { BarChart3, FileCode, FileText, Filter, MoreHorizontal, Network, RefreshCw, Share2, Link as LinkIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Switch } from '@/components/ui/switch'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { KGStatsResponse } from '@/types'

import type { GraphConfBucket } from '../graph-page-utils'
import { GraphFiltersPopover } from './graph-filters-popover'
import { GraphSearchOverlay } from './graph-search-overlay'
import { GraphStatusBanners } from './graph-status-banners'

type GraphFilterOption = Readonly<{
  value: string
  count: number
}>

type GraphPageHeaderProps = Readonly<{
  fileName: string | null
  dataSource: 'live' | 'file'
  viewMode: '2d' | '3d'
  kgStats: KGStatsResponse | null
  graphNodeCount: number
  graphLinkCount: number
  activeGraphFilterCount: number
  searchOpen: boolean
  searchInputRef: RefObject<HTMLInputElement | null>
  searchTerm: string
  highlightedMatchCount: number
  onSearchTermChange: (value: string) => void
  isPathMode: boolean
  hasPathStart: boolean
  hasPathEnd: boolean
  isConnectMode: boolean
  connectSourceLabel: string | null
  isExplainMode: boolean
  currentStepIndex: number
  explainStepCount: number
  onExitPathMode: () => void
  onExitConnectMode: () => void
  onExitExplainMode: () => void
  includeEntityLinks: boolean
  includeRelationLinks: boolean
  minSharedEvents: number
  onToggleEntityLinks: () => void
  onToggleRelationLinks: () => void
  onCycleMinSharedEvents: () => void
  onExportGraphML: () => void
  isLoading: boolean
  filtersOpen: boolean
  onFiltersOpenChange: (open: boolean) => void
  entityTypeQuery: string
  onEntityTypeQueryChange: (value: string) => void
  entityTypeFilters: string[]
  filteredEntityTypes: GraphFilterOption[]
  onEntityTypeCheckedChange: (value: string, checked: boolean) => void
  onResetEntityTypeFilters: () => void
  predicateQuery: string
  onPredicateQueryChange: (value: string) => void
  predicateFilters: string[]
  filteredPredicates: GraphFilterOption[]
  onPredicateCheckedChange: (value: string, checked: boolean) => void
  onResetPredicateFilters: () => void
  confidenceBucketFilters: GraphConfBucket[]
  onResetConfidenceBuckets: () => void
  onToggleConfidenceBucket: (bucket: GraphConfBucket) => void
  onResetGraphFilters: () => void
  onRefreshLiveData: () => void
  onOpenGraphPicker: () => void
  onTriggerTraceUpload: () => void
  traceFileInputRef: RefObject<HTMLInputElement | null>
  onTraceFileUpload: ChangeEventHandler<HTMLInputElement>
  onTriggerManualKgUpload: () => void
  manualKgFileInputRef: RefObject<HTMLInputElement | null>
  onManualKgFileUpload: ChangeEventHandler<HTMLInputElement>
}>

export function GraphPageHeader({
  fileName,
  dataSource,
  viewMode,
  kgStats,
  graphNodeCount,
  graphLinkCount,
  activeGraphFilterCount,
  searchOpen,
  searchInputRef,
  searchTerm,
  highlightedMatchCount,
  onSearchTermChange,
  isPathMode,
  hasPathStart,
  hasPathEnd,
  isConnectMode,
  connectSourceLabel,
  isExplainMode,
  currentStepIndex,
  explainStepCount,
  onExitPathMode,
  onExitConnectMode,
  onExitExplainMode,
  includeEntityLinks,
  includeRelationLinks,
  minSharedEvents,
  onToggleEntityLinks,
  onToggleRelationLinks,
  onCycleMinSharedEvents,
  onExportGraphML,
  isLoading,
  filtersOpen,
  onFiltersOpenChange,
  entityTypeQuery,
  onEntityTypeQueryChange,
  entityTypeFilters,
  filteredEntityTypes,
  onEntityTypeCheckedChange,
  onResetEntityTypeFilters,
  predicateQuery,
  onPredicateQueryChange,
  predicateFilters,
  filteredPredicates,
  onPredicateCheckedChange,
  onResetPredicateFilters,
  confidenceBucketFilters,
  onResetConfidenceBuckets,
  onToggleConfidenceBucket,
  onResetGraphFilters,
  onRefreshLiveData,
  onOpenGraphPicker,
  onTriggerTraceUpload,
  traceFileInputRef,
  onTraceFileUpload,
  onTriggerManualKgUpload,
  manualKgFileInputRef,
  onManualKgFileUpload,
}: GraphPageHeaderProps) {
  let liveControls: ReactNode = null
  if (dataSource === 'live') {
    liveControls = (
      <>
        <div className="hidden shrink-0 items-center gap-2 2xl:flex">
          <div className="flex items-center gap-2 rounded-full border border-border/60 bg-background/76 px-2.5 py-1.5 shadow-none">
            <div className="flex items-center gap-1.5 text-xs font-medium text-foreground/88">
              <LinkIcon className={cn('h-3.5 w-3.5', includeEntityLinks ? 'text-info' : 'text-muted-foreground')} />
              <span>实体</span>
            </div>
            <Switch
              checked={includeEntityLinks}
              onCheckedChange={() => onToggleEntityLinks()}
              aria-label="切换实体连线"
              className="scale-[0.82] data-[state=checked]:bg-info"
            />
          </div>
          <div className="flex items-center gap-2 rounded-full border border-border/60 bg-background/76 px-2.5 py-1.5 shadow-none">
            <div className="flex items-center gap-1.5 text-xs font-medium text-foreground/88">
              <Network className={cn('h-3.5 w-3.5', includeRelationLinks ? 'text-teal-600 dark:text-teal-300' : 'text-muted-foreground')} />
              <span>关系</span>
            </div>
            <Switch
              checked={includeRelationLinks}
              onCheckedChange={() => onToggleRelationLinks()}
              aria-label="切换关系连线"
              className="scale-[0.82] data-[state=checked]:bg-teal-500"
            />
          </div>
        </div>
        <TooltipProvider delayDuration={120}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                onClick={onCycleMinSharedEvents}
                className="shrink-0 text-muted-foreground hover:text-info hover:bg-info/10"
              >
                <Filter className="w-4 h-4 mr-2" />
                Co≥{minSharedEvents}
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom" align="center" className="max-w-[240px] text-[11px] leading-5">
              共现阈值。仅保留至少在 {minSharedEvents} 个事件中共同出现的关系连线；点击可在 1-4 之间切换。
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </>
    )
  }

  return (
    <header className="absolute top-0 left-0 right-0 z-20 flex h-16 items-center gap-3 border-b border-border/60 bg-[linear-gradient(135deg,hsl(var(--card)/0.98),hsl(var(--muted)/0.34))] px-4 shadow-[0_18px_46px_-40px_rgba(15,23,42,0.46)] pointer-events-none lg:px-6">
      <div
        className="pointer-events-none absolute inset-y-3 left-0 w-1 rounded-r-full bg-[linear-gradient(180deg,hsl(var(--info)),hsl(var(--primary)))]"
        aria-hidden="true"
      />
      <div className="pointer-events-auto flex shrink-0 items-center gap-2.5">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-[15px] border border-info/18 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--info)/0.10))] text-info shadow-[inset_0_1px_0_hsl(var(--background)),0_14px_30px_-24px_hsl(var(--info)/0.75)]">
          <PageTitleIcon name="knowledge-graph" className="size-7" />
        </div>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-foreground">
          <span className="bg-[linear-gradient(90deg,hsl(var(--foreground)),hsl(var(--info))_92%)] bg-clip-text text-transparent">
            知识图谱
          </span>
        </h1>
        <span className="shrink-0 rounded-full border border-blue-500/25 bg-blue-500/10 px-2.5 py-1 text-[11px] font-semibold text-blue-600 shadow-sm dark:text-blue-300">
          {viewMode === '3d' ? '3D 图谱' : '2D 图谱'}
        </span>
      </div>

      <div className="pointer-events-auto hidden min-w-0 shrink-0 items-center gap-2 xl:flex">
        {fileName ? (
          <div className="flex max-w-[150px] items-center gap-2 rounded-full border border-border bg-muted/50 px-3 py-1.5 text-xs font-medium text-muted-foreground">
            <FileCode className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span className="truncate">{fileName}</span>
          </div>
        ) : null}

        {dataSource === 'live' && kgStats ? (
          <div className="flex items-center gap-2 rounded-full border border-border bg-muted/50 px-3 py-1.5 text-xs font-medium text-muted-foreground">
            <BarChart3 className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="font-mono">
              E:{kgStats.events} N:{kgStats.entities} L:{kgStats.links}
            </span>
          </div>
        ) : null}
      </div>

      <div className="pointer-events-auto flex min-w-[300px] flex-1 justify-center">
        <GraphSearchOverlay
          open={searchOpen}
          inputRef={searchInputRef}
          searchTerm={searchTerm}
          highlightedMatchCount={highlightedMatchCount}
          onSearchTermChange={onSearchTermChange}
        />
      </div>

      <GraphStatusBanners
        isPathMode={isPathMode}
        hasPathStart={hasPathStart}
        hasPathEnd={hasPathEnd}
        isConnectMode={isConnectMode}
        connectSourceLabel={connectSourceLabel}
        isExplainMode={isExplainMode}
        currentStepIndex={currentStepIndex}
        explainStepCount={explainStepCount}
        onExitPathMode={onExitPathMode}
        onExitConnectMode={onExitConnectMode}
        onExitExplainMode={onExitExplainMode}
      />

      <div className="pointer-events-auto ml-auto flex shrink-0 items-center gap-2">
        {liveControls}

        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className="shrink-0 gap-2 border-border/60 bg-background/78 text-foreground/88 shadow-none hover:bg-background hover:text-foreground active:bg-background"
            >
              <MoreHorizontal className="h-4 w-4" />
              图谱工具
              {activeGraphFilterCount > 0 ? (
                <span className="ml-0.5 rounded-full bg-info/12 px-1.5 py-0.5 text-[10px] font-semibold text-info">
                  {activeGraphFilterCount}
                </span>
              ) : null}
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-[390px] p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-foreground">图谱工具</div>
                <div className="mt-0.5 text-[11px] text-muted-foreground">
                  KG JSON/JSONL 是唯一外部图谱导入方式
                </div>
              </div>
              <div className="rounded-full border border-border/60 bg-muted/45 px-2.5 py-1 text-[11px] font-mono text-muted-foreground">
                {graphNodeCount}N / {graphLinkCount}L
              </div>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={onTriggerManualKgUpload}
                disabled={isLoading}
                className="col-span-2 h-auto justify-start gap-3 rounded-xl border-info/20 bg-info/10 px-3 py-3 text-left text-info shadow-none hover:bg-info/15 hover:text-info"
                title="导入人工治理后的 KG JSON / JSONL 到后端图谱库，并自动创建事件与向量索引"
              >
                <Network className="h-4 w-4 shrink-0" />
                <span className="min-w-0">
                  <span className="block text-[13px] font-semibold leading-4">导入 KG JSON / JSONL</span>
                  <span className="mt-0.5 block text-[11px] font-normal leading-4 text-muted-foreground">
                    实体、关系、证据入库并自动关联事件
                  </span>
                </span>
              </Button>

              {dataSource === 'live' ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={onExportGraphML}
                  disabled={isLoading}
                  className="justify-start gap-2 border-border/60 bg-background/70 text-muted-foreground shadow-none hover:bg-info/10 hover:text-info"
                >
                  <FileCode className="h-4 w-4" />
                  导出
                </Button>
              ) : null}

              {graphNodeCount > 0 || activeGraphFilterCount > 0 ? (
                <div className="[&>button]:h-9 [&>button]:w-full [&>button]:justify-start [&>button]:gap-2 [&>button]:rounded-md [&>button]:border [&>button]:border-border/60 [&>button]:bg-background/70 [&>button]:px-3 [&>button]:shadow-none">
                  <GraphFiltersPopover
                    open={filtersOpen}
                    onOpenChange={onFiltersOpenChange}
                    activeGraphFilterCount={activeGraphFilterCount}
                    graphNodeCount={graphNodeCount}
                    graphLinkCount={graphLinkCount}
                    entityTypeQuery={entityTypeQuery}
                    onEntityTypeQueryChange={onEntityTypeQueryChange}
                    entityTypeFilters={entityTypeFilters}
                    filteredEntityTypes={filteredEntityTypes}
                    onEntityTypeCheckedChange={onEntityTypeCheckedChange}
                    onResetEntityTypeFilters={onResetEntityTypeFilters}
                    predicateQuery={predicateQuery}
                    onPredicateQueryChange={onPredicateQueryChange}
                    predicateFilters={predicateFilters}
                    filteredPredicates={filteredPredicates}
                    onPredicateCheckedChange={onPredicateCheckedChange}
                    onResetPredicateFilters={onResetPredicateFilters}
                    confidenceBucketFilters={confidenceBucketFilters}
                    onResetConfidenceBuckets={onResetConfidenceBuckets}
                    onToggleConfidenceBucket={onToggleConfidenceBucket}
                    onResetGraphFilters={onResetGraphFilters}
                  />
                </div>
              ) : null}

              <Button
                variant="outline"
                size="sm"
                onClick={onOpenGraphPicker}
                className="justify-start gap-2 border-border/60 bg-background/70 text-muted-foreground shadow-none hover:bg-muted/60 hover:text-foreground"
              >
                <Share2 className="h-4 w-4" />
                {dataSource === 'live' ? '切换图谱' : '选择图谱'}
              </Button>

              <Button
                variant="outline"
                size="sm"
                onClick={onRefreshLiveData}
                disabled={isLoading}
                className="justify-start gap-2 border-border/60 bg-background/70 text-muted-foreground shadow-none hover:bg-sky-500/10 hover:text-sky-600 dark:hover:text-sky-300"
              >
                <RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin motion-reduce:animate-none')} />
                {isLoading ? '加载中' : '刷新'}
              </Button>

              <Button
                variant="outline"
                size="sm"
                onClick={onTriggerTraceUpload}
                className="justify-start gap-2 border-border/60 bg-background/70 text-muted-foreground shadow-none hover:bg-teal-500/10 hover:text-teal-600 dark:hover:text-teal-300"
                title="导入 RAG trace JSON（回放检索路径）"
              >
                <FileText className="h-4 w-4" />
                Trace
              </Button>
            </div>
          </PopoverContent>
        </Popover>
        <input
          ref={traceFileInputRef}
          type="file"
          accept=".json,application/json"
          className="hidden"
          onChange={onTraceFileUpload}
        />
        <input
          ref={manualKgFileInputRef}
          type="file"
          accept=".json,.jsonl,application/json"
          className="hidden"
          onChange={onManualKgFileUpload}
        />
      </div>
    </header>
  )
}
