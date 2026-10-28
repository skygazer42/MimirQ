'use client'

import type { ChangeEventHandler, RefObject } from 'react'
import { FileCode, FileText, GitCompare, MoreHorizontal, Network, RefreshCw, Share2, Wrench } from '@/components/icons'
import { Link } from '@/i18n/navigation'
import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import type { UseGraphPageStateResult } from '../use-graph-page-state'
import type { UseGraphDisplayFiltersResult } from '../use-graph-display-filters'
import { GraphFiltersPopover } from './graph-filters-popover'
import styles from './graph-workspace.module.css'

type GraphPageHeaderProps = Readonly<{
  fileName: string | null
  dataSource: 'live' | 'file'
  graphNodeCount: number
  isLoading: boolean
  includeEntityLinks: boolean
  includeRelationLinks: boolean
  minSharedEvents: number
  onToggleEntityLinks: () => void
  onToggleRelationLinks: () => void
  onCycleMinSharedEvents: () => void
  onExportGraphML: () => void
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
  fileName, dataSource, graphNodeCount, isLoading,
  includeEntityLinks, includeRelationLinks, minSharedEvents,
  onToggleEntityLinks, onToggleRelationLinks, onCycleMinSharedEvents, onExportGraphML,
  onRefreshLiveData, onOpenGraphPicker, onTriggerTraceUpload, traceFileInputRef,
  onTraceFileUpload, onTriggerManualKgUpload, manualKgFileInputRef, onManualKgFileUpload,
}: GraphPageHeaderProps) {
  return <header className={styles.header}>
    <div className={styles.heading}><PageTitleIcon name="knowledge-graph" /><h1>知识图谱</h1></div>
    <span className={styles.scopeLabel} title={fileName || '尚未选择图谱'}>{fileName === '知识图谱' ? '全部数据' : fileName || '尚未选择图谱'}</span>
    <div className={styles.headerActions}>
      <Button variant="outline" onClick={onOpenGraphPicker}><Share2 /><span>选择图谱</span></Button>
      {dataSource === 'live' && graphNodeCount > 0 ? <Button variant="outline" onClick={onExportGraphML} disabled={isLoading} aria-label="导出 GraphML"><FileCode /><span className={styles.buttonLabel}>导出</span></Button> : null}
      <Popover><PopoverTrigger asChild><Button variant="ghost" className={styles.iconOnly} aria-label="图谱工具"><MoreHorizontal /></Button></PopoverTrigger>
        <PopoverContent align="end" className={styles.toolsMenu}>
          <button type="button" onClick={onTriggerManualKgUpload} disabled={isLoading}><Network />导入 KG JSON / JSONL</button>
          <button type="button" onClick={onTriggerTraceUpload} disabled={isLoading}><FileText />导入检索回放</button>
          <button type="button" onClick={onRefreshLiveData} disabled={isLoading}><RefreshCw className={cn(isLoading && 'animate-spin motion-reduce:animate-none')} />{isLoading ? '正在加载…' : '重新加载图谱'}</button>
          <div className={styles.menuDivider} />
          {dataSource === 'live' ? <><label className={styles.toolSwitch}>实体连线<Switch aria-label="切换实体连线" checked={includeEntityLinks} onCheckedChange={onToggleEntityLinks} /></label><label className={styles.toolSwitch}>关系连线<Switch aria-label="切换关系连线" checked={includeRelationLinks} onCheckedChange={onToggleRelationLinks} /></label><button type="button" onClick={onCycleMinSharedEvents}>共现阈值 ≥ {minSharedEvents}</button><div className={styles.menuDivider} /></> : null}
          <Link href="/graph/diagnostics"><Wrench />图谱诊断</Link>
          <Link href="/graph/snapshots"><GitCompare />图谱快照</Link>
        </PopoverContent>
      </Popover>
      <input ref={traceFileInputRef} type="file" accept=".json,application/json" className="hidden" aria-label="导入检索回放文件" onChange={onTraceFileUpload} />
      <input ref={manualKgFileInputRef} type="file" accept=".json,.jsonl,application/json" className="hidden" aria-label="导入知识图谱文件" onChange={onManualKgFileUpload} />
    </div>
  </header>
}

export function GraphWorkspaceFilters({ state, filters }: Readonly<{ state: UseGraphPageStateResult; filters: UseGraphDisplayFiltersResult }>) {
  return <GraphFiltersPopover
    open={state.filtersOpen} onOpenChange={state.setFiltersOpen}
    activeGraphFilterCount={filters.activeGraphFilterCount}
    graphNodeCount={filters.displayGraphData.nodes.length} graphLinkCount={filters.displayGraphData.links.length}
    entityTypeQuery={state.entityTypeQuery} onEntityTypeQueryChange={state.setEntityTypeQuery}
    entityTypeFilters={state.entityTypeFilters} filteredEntityTypes={filters.filteredEntityTypes}
    onEntityTypeCheckedChange={filters.handleEntityTypeCheckedChange} onResetEntityTypeFilters={() => state.setEntityTypeFilters([])}
    predicateQuery={state.predicateQuery} onPredicateQueryChange={state.setPredicateQuery}
    predicateFilters={state.predicateFilters} filteredPredicates={filters.filteredPredicates}
    onPredicateCheckedChange={filters.handlePredicateCheckedChange} onResetPredicateFilters={() => state.setPredicateFilters([])}
    confidenceBucketFilters={state.confidenceBucketFilters} onResetConfidenceBuckets={() => state.setConfidenceBucketFilters([])}
    onToggleConfidenceBucket={filters.toggleConfidenceBucket} onResetGraphFilters={filters.resetGraphFilters}
  />
}
