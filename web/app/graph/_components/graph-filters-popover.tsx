'use client'

import { SlidersHorizontal } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

import type { GraphConfBucket } from '../graph-page-utils'

type GraphFilterOption = Readonly<{
  value: string
  count: number
}>

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
          className={activeGraphFilterCount > 0 ? 'bg-primary/10 text-primary hover:text-primary' : 'text-muted-foreground hover:text-foreground hover:bg-muted/60'}
          title="图谱筛选：predicate / entity type / confidence bucket"
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
      <PopoverContent align="end" className="w-[420px] p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <SlidersHorizontal className="w-4 h-4 text-muted-foreground" />
              <div className="text-sm font-semibold text-foreground">图谱筛选</div>
              <div className="text-[11px] text-muted-foreground font-mono">
                {graphNodeCount}N / {graphLinkCount}L
              </div>
            </div>
            <div className="mt-1 text-[11px] text-muted-foreground">
              Predicate 仅对关系边生效；Type 仅对实体节点生效。
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
          <div>
            <div className="flex items-center justify-between">
              <div className="text-[11px] font-semibold text-muted-foreground uppercase">Entity Type</div>
              {entityTypeFilters.length === 0 ? (
                <span className="text-[11px] text-muted-foreground">Any</span>
              ) : (
                <button
                  type="button"
                  className="text-[11px] text-primary hover:underline"
                  onClick={onResetEntityTypeFilters}
                >
                  Any
                </button>
              )}
            </div>
            <Input
              value={entityTypeQuery}
              onChange={(e) => onEntityTypeQueryChange(e.target.value)}
              placeholder="Search types…"
              className="mt-2 h-8 text-xs"
            />
            <div className="mt-2 max-h-36 overflow-y-auto overscroll-contain no-scrollbar pr-1 space-y-1">
              {filteredEntityTypes.length === 0 ? (
                <div className="text-xs text-muted-foreground">No entity types found</div>
              ) : (
                filteredEntityTypes.map((item) => {
                  const checked = entityTypeFilters.includes(item.value)
                  return (
                    <label
                      key={item.value}
                      className="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-muted/60"
                    >
                      <Checkbox
                        checked={checked}
                        onCheckedChange={(next) => onEntityTypeCheckedChange(item.value, !!next)}
                      />
                      <span className="flex-1 min-w-0 truncate text-xs text-foreground">{item.value}</span>
                      <span className="text-[11px] font-mono text-muted-foreground">{item.count}</span>
                    </label>
                  )
                })
              )}
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between">
              <div className="text-[11px] font-semibold text-muted-foreground uppercase">Predicate</div>
              {predicateFilters.length === 0 ? (
                <span className="text-[11px] text-muted-foreground">Any</span>
              ) : (
                <button
                  type="button"
                  className="text-[11px] text-primary hover:underline"
                  onClick={onResetPredicateFilters}
                >
                  Any
                </button>
              )}
            </div>
            <Input
              value={predicateQuery}
              onChange={(e) => onPredicateQueryChange(e.target.value)}
              placeholder="Search predicates…"
              className="mt-2 h-8 text-xs"
            />
            <div className="mt-2 max-h-36 overflow-y-auto overscroll-contain no-scrollbar pr-1 space-y-1">
              {filteredPredicates.length === 0 ? (
                <div className="text-xs text-muted-foreground">No predicates found</div>
              ) : (
                filteredPredicates.map((item) => {
                  const checked = predicateFilters.includes(item.value)
                  return (
                    <label
                      key={item.value}
                      className="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-muted/60"
                    >
                      <Checkbox
                        checked={checked}
                        onCheckedChange={(next) => onPredicateCheckedChange(item.value, !!next)}
                      />
                      <span className="flex-1 min-w-0 truncate text-xs text-foreground">{item.value}</span>
                      <span className="text-[11px] font-mono text-muted-foreground">{item.count}</span>
                    </label>
                  )
                })
              )}
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between">
              <div className="text-[11px] font-semibold text-muted-foreground uppercase">Confidence</div>
              {confidenceBucketFilters.length === 0 ? (
                <span className="text-[11px] text-muted-foreground">Any</span>
              ) : (
                <button
                  type="button"
                  className="text-[11px] text-primary hover:underline"
                  onClick={onResetConfidenceBuckets}
                >
                  Any
                </button>
              )}
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant={confidenceBucketFilters.length === 0 ? 'info' : 'outline'}
                className="h-7 px-2 text-xs"
                onClick={onResetConfidenceBuckets}
              >
                Any
              </Button>
              <Button
                type="button"
                size="sm"
                variant={confidenceBucketFilters.includes('high') ? 'info' : 'outline'}
                className="h-7 px-2 text-xs"
                onClick={() => onToggleConfidenceBucket('high')}
              >
                High (≥0.8)
              </Button>
              <Button
                type="button"
                size="sm"
                variant={confidenceBucketFilters.includes('medium') ? 'info' : 'outline'}
                className="h-7 px-2 text-xs"
                onClick={() => onToggleConfidenceBucket('medium')}
              >
                Mid (0.5-0.8)
              </Button>
              <Button
                type="button"
                size="sm"
                variant={confidenceBucketFilters.includes('low') ? 'info' : 'outline'}
                className="h-7 px-2 text-xs"
                onClick={() => onToggleConfidenceBucket('low')}
              >
                Low (&lt;0.5)
              </Button>
            </div>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}
