'use client'

import { SlidersHorizontal } from '@/components/icons'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

import { GRAPH_CONFIDENCE_THRESHOLDS, type GraphConfBucket } from '../graph-page-utils'

type GraphFilterOption = Readonly<{
  value: string
  count: number
}>

const CONFIDENCE_OPTIONS = [
  ['high', `高（≥${GRAPH_CONFIDENCE_THRESHOLDS.high}）`],
  ['medium', `中（${GRAPH_CONFIDENCE_THRESHOLDS.medium} ≤ 置信度 < ${GRAPH_CONFIDENCE_THRESHOLDS.high}）`],
  ['low', `低（<${GRAPH_CONFIDENCE_THRESHOLDS.medium}）`],
] as const

function GraphFilterOptions({
  label,
  query,
  selected,
  options,
  onQueryChange,
  onCheckedChange,
  onReset,
}: Readonly<{
  label: string
  query: string
  selected: readonly string[]
  options: readonly GraphFilterOption[]
  onQueryChange: (query: string) => void
  onCheckedChange: (value: string, checked: boolean) => void
  onReset: () => void
}>) {
  return (
    <section aria-label={label}>
      <div className="flex items-center justify-between">
        <h3 className="text-[11px] font-semibold text-muted-foreground">{label}</h3>
        {selected.length === 0 ? (
          <span className="text-[11px] text-muted-foreground">不限</span>
        ) : (
          <button type="button" className="text-[11px] text-primary hover:underline" onClick={onReset}>
            清除{label}筛选
          </button>
        )}
      </div>
      <Input
        aria-label={`搜索${label}`}
        value={query}
        onChange={(event) => onQueryChange(event.currentTarget.value)}
        placeholder={`搜索${label}…`}
        className="mt-2 h-8 text-xs"
      />
      <div className="mt-2 max-h-36 space-y-1 overflow-y-auto pr-1 no-scrollbar">
        {options.length === 0 ? (
          <p className="text-xs text-muted-foreground">没有匹配的{label}</p>
        ) : (
          options.map((option) => (
            <label key={option.value} className="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-muted/60">
              <Checkbox
                checked={selected.includes(option.value)}
                onCheckedChange={(checked) => onCheckedChange(option.value, checked === true)}
              />
              <span className="min-w-0 flex-1 truncate text-xs text-foreground">{option.value}</span>
              <span className="font-mono text-[11px] text-muted-foreground">{option.count}</span>
            </label>
          ))
        )}
      </div>
    </section>
  )
}

type GraphFiltersPopoverProps = Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  activeGraphFilterCount: number
  graphNodeCount: number
  graphLinkCount: number
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
}>

export function GraphFiltersPopover({
  open,
  onOpenChange,
  activeGraphFilterCount,
  graphNodeCount,
  graphLinkCount,
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
}: GraphFiltersPopoverProps) {
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className={
            activeGraphFilterCount > 0
              ? 'bg-primary/10 text-primary hover:text-primary'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted/60'
          }
          title="筛选实体类型、关系谓词和置信度"
        >
          <SlidersHorizontal className="w-4 h-4 mr-2" />
          筛选
          {activeGraphFilterCount > 0 ? (
            <Badge variant="soft" className="ml-2 px-2 py-0.5 text-[11px]">
              {activeGraphFilterCount}
            </Badge>
          ) : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        aria-label="图谱筛选"
        className="max-h-[var(--radix-popover-content-available-height)] w-[420px] max-w-[var(--radix-popover-content-available-width)] overflow-y-auto p-4"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <SlidersHorizontal className="w-4 h-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold text-foreground">图谱筛选</h2>
              <div className="text-[11px] text-muted-foreground font-mono">
                {graphNodeCount} 个节点 · {graphLinkCount} 条连线
              </div>
            </div>
            <div className="mt-1 text-[11px] text-muted-foreground">
              实体类型筛选用于实体节点，关系谓词筛选用于关系连线。
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={onResetGraphFilters}
              disabled={activeGraphFilterCount === 0 && !entityTypeQuery && !predicateQuery}
            >
              清除
            </Button>
          </div>
        </div>

        <div className="mt-4 space-y-5">
          <GraphFilterOptions
            label="实体类型"
            query={entityTypeQuery}
            selected={entityTypeFilters}
            options={filteredEntityTypes}
            onQueryChange={onEntityTypeQueryChange}
            onCheckedChange={onEntityTypeCheckedChange}
            onReset={onResetEntityTypeFilters}
          />
          <GraphFilterOptions
            label="关系谓词"
            query={predicateQuery}
            selected={predicateFilters}
            options={filteredPredicates}
            onQueryChange={onPredicateQueryChange}
            onCheckedChange={onPredicateCheckedChange}
            onReset={onResetPredicateFilters}
          />
          <section aria-label="置信度">
            <h3 className="text-[11px] font-semibold text-muted-foreground">置信度</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant={confidenceBucketFilters.length === 0 ? 'info' : 'outline'}
                className="h-7 px-2 text-xs"
                aria-pressed={confidenceBucketFilters.length === 0}
                onClick={onResetConfidenceBuckets}
              >
                不限
              </Button>
              {CONFIDENCE_OPTIONS.map(([bucket, label]) => {
                const pressed = confidenceBucketFilters.includes(bucket)
                return (
                  <Button
                    key={bucket}
                    type="button"
                    size="sm"
                    variant={pressed ? 'info' : 'outline'}
                    className="h-7 px-2 text-xs"
                    aria-pressed={pressed}
                    onClick={() => onToggleConfidenceBucket(bucket)}
                  >
                    {label}
                  </Button>
                )
              })}
            </div>
          </section>
        </div>
      </PopoverContent>
    </Popover>
  )
}
