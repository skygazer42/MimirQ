'use client'

import type { ChangeEventHandler, RefObject } from 'react'

import { BarChart3, FileCode, FileText, Filter, Network, RefreshCw, Share2, Upload, Link as LinkIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
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
  onTriggerFileUpload: () => void
  fileInputRef: RefObject<HTMLInputElement | null>
  onFileUpload: ChangeEventHandler<HTMLInputElement>
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
  onTriggerFileUpload,
  fileInputRef,
  onFileUpload,
}: GraphPageHeaderProps) {
  return (
    <header className="absolute top-0 left-0 right-0 z-20 flex h-16 items-center justify-between border-b border-border/50 bg-card px-6 pointer-events-none">
      <div className="flex items-center gap-3 pointer-events-auto">
        <div className="flex items-center gap-2">
          <h1 className="text-3xl font-bold text-foreground">知识图谱</h1>
          <span className="rounded-full border border-blue-500/25 bg-blue-500/10 px-2.5 py-1 text-[11px] font-semibold text-blue-600 shadow-sm dark:text-blue-300">
            {viewMode === '3d' ? '3D 图谱' : '2D 图谱'}
          </span>
        </div>
      </div>

      <GraphSearchOverlay
        open={searchOpen}
        inputRef={searchInputRef}
        searchTerm={searchTerm}
        highlightedMatchCount={highlightedMatchCount}
        onSearchTermChange={onSearchTermChange}
      />

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

      <div className="flex items-center gap-3 pointer-events-auto">
        {fileName ? (
          <div className="hidden items-center gap-2 rounded-full border border-border bg-muted/50 px-3 py-1.5 text-xs font-medium text-muted-foreground md:flex">
            <FileCode className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="max-w-[150px] truncate">{fileName}</span>
          </div>
        ) : null}

        {dataSource === 'live' && kgStats ? (
          <div className="hidden items-center gap-2 rounded-full border border-border bg-muted/50 px-3 py-1.5 text-xs font-medium text-muted-foreground lg:flex">
            <BarChart3 className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="font-mono">
              E:{kgStats.events} N:{kgStats.entities} L:{kgStats.links}
            </span>
          </div>
        ) : null}

        {dataSource === 'live' ? (
          <>
            <div className="hidden items-center gap-2 xl:flex">
              <div className="flex items-center gap-3 rounded-lg border border-border/60 bg-background/76 px-3 py-1.5 shadow-none">
                <div className="flex items-center gap-2 text-xs font-medium text-foreground/88">
                  <LinkIcon className={cn('h-3.5 w-3.5', includeEntityLinks ? 'text-info' : 'text-muted-foreground')} />
                  <span>实体连线</span>
                </div>
                <Switch
                  checked={includeEntityLinks}
                  onCheckedChange={() => onToggleEntityLinks()}
                  aria-label="切换实体连线"
                  className="scale-[0.82] data-[state=checked]:bg-info"
                />
              </div>
              <div className="flex items-center gap-3 rounded-lg border border-border/60 bg-background/76 px-3 py-1.5 shadow-none">
                <div className="flex items-center gap-2 text-xs font-medium text-foreground/88">
                  <Network className={cn('h-3.5 w-3.5', includeRelationLinks ? 'text-teal-600 dark:text-teal-300' : 'text-muted-foreground')} />
                  <span>关系连线</span>
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
                    className="text-muted-foreground hover:text-info hover:bg-info/10"
                    title="共现阈值（点击循环）"
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
            <Button
              variant="ghost"
              size="sm"
              onClick={onExportGraphML}
              disabled={isLoading}
              className="text-muted-foreground hover:text-info hover:bg-info/10"
              title="导出 GraphML"
            >
              <FileCode className="w-4 h-4 mr-2" />
              导出
            </Button>
          </>
        ) : null}

        {graphNodeCount > 0 || activeGraphFilterCount > 0 ? (
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
        ) : null}

        <div className="mx-1 hidden h-6 w-px bg-muted sm:block" />

        <Button
          variant="outline"
          size="sm"
          onClick={onOpenGraphPicker}
          className="gap-2 border-border/60 bg-background/70 text-foreground/85 shadow-none hover:bg-background/70 hover:text-foreground/85 active:bg-background/70"
        >
          <Share2 className="w-4 h-4" />
          {dataSource === 'live' ? '切换图谱' : '选择图谱'}
        </Button>

        <Button
          variant="ghost"
          size="sm"
          onClick={onRefreshLiveData}
          disabled={isLoading}
          className="text-muted-foreground hover:text-sky-600 dark:hover:text-sky-300 hover:bg-sky-500/10 dark:hover:bg-sky-500/20"
        >
          <RefreshCw className={cn('w-4 h-4 mr-2', isLoading && 'animate-spin motion-reduce:animate-none')} />
          {isLoading ? '加载中...' : '刷新'}
        </Button>

        <Button
          variant="ghost"
          size="sm"
          onClick={onTriggerTraceUpload}
          className="text-muted-foreground hover:text-teal-600 dark:hover:text-teal-300 hover:bg-teal-500/10 dark:hover:bg-teal-500/20"
          title="导入 RAG trace JSON（回放检索路径）"
        >
          <FileText className="w-4 h-4 mr-2" />
          Trace
        </Button>
        <input
          ref={traceFileInputRef}
          type="file"
          accept=".json,application/json"
          className="hidden"
          onChange={onTraceFileUpload}
        />

        <Button variant="outline" size="sm" className="gap-2 border-border/60" onClick={onTriggerFileUpload}>
          <Upload className="w-4 h-4" />
          GraphML
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".graphml,.xml"
          className="hidden"
          onChange={onFileUpload}
        />
      </div>
    </header>
  )
}
