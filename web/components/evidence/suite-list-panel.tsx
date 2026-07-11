'use client'

import { Plus, RefreshCw, ShieldCheck } from 'lucide-react'

import type { EvidenceSuite } from '@/types'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import { SearchInput } from '@/components/ui/search-input'

type SuiteListPanelProps = {
  datasetLabel: string
  suiteQuery: string
  onSuiteQueryChange: (value: string) => void
  onRefresh: () => void
  suitesLoading: boolean
  includeArchivedSuites: boolean
  onIncludeArchivedSuitesChange: (value: boolean) => void
  suitesError: string | null
  filteredSuites: EvidenceSuite[]
  selectedSuiteId: string
  onCreateSuite: () => void
  onSelectSuite: (suiteId: string) => void
}

export function SuiteListPanel({
  datasetLabel,
  suiteQuery,
  onSuiteQueryChange,
  onRefresh,
  suitesLoading,
  includeArchivedSuites,
  onIncludeArchivedSuitesChange,
  suitesError,
  filteredSuites,
  selectedSuiteId,
  onCreateSuite,
  onSelectSuite,
}: Readonly<SuiteListPanelProps>) {
  let suitesContent: React.ReactNode
  if (suitesLoading) {
    suitesContent = <div className="text-xs text-muted-foreground">加载中…</div>
  } else if (filteredSuites.length) {
    suitesContent = (
      <>
        {filteredSuites.map((suite) => {
          const active = suite.id === selectedSuiteId
          const counts = suite.item_counts || {}
          const total = Number(counts.total || 0)
          const approved = Number(counts.approved || 0)
          const tags = Array.isArray(suite.tags) ? suite.tags : []
          const overflowCount = tags.length - 3
          let tagContent: React.ReactNode = null
          if (tags.length) {
            tagContent = (
              <div className="mt-2 flex flex-wrap gap-1">
                {tags.slice(0, 3).map((tag) => (
                  <Badge key={tag} variant="secondary" className="text-[11px] font-mono">
                    {tag}
                  </Badge>
                ))}
                {overflowCount > 0 ? (
                  <span className="text-[11px] font-mono text-muted-foreground">
                    +{overflowCount}
                  </span>
                ) : null}
              </div>
            )
          }

          return (
            <button
              key={suite.id}
              type="button"
              className={cn(
                'w-full rounded-lg border px-3 py-2 text-left transition-colors',
                active ? 'border-primary/40 bg-primary/5' : 'border-border hover:bg-muted/30'
              )}
              onClick={() => onSelectSuite(String(suite.id))}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-foreground">{suite.name}</div>
                  {suite.description ? (
                    <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground text-pretty">
                      {suite.description}
                    </div>
                  ) : null}
                </div>
                <div className="flex flex-shrink-0 flex-col items-end gap-1">
                  <Badge variant="outline" className="font-mono tabular-nums">
                    {total}
                  </Badge>
                  {approved ? (
                    <Badge variant="soft" className="font-mono tabular-nums">
                      approved {approved}
                    </Badge>
                  ) : null}
                </div>
              </div>
              {tagContent}
            </button>
          )
        })}
      </>
    )
  } else {
    suitesContent = (
      <div className="text-xs text-muted-foreground text-pretty">
        暂无 Suite。点击「新建」创建一个 Evidence Suite。
      </div>
    )
  }

  return (
    <Panel className="p-4 xl:col-span-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <ShieldCheck className="size-4 text-muted-foreground" aria-hidden="true" />
            Evidence Suites
          </div>
          <div className="mt-1 text-xs text-muted-foreground text-pretty">
            数据集：{datasetLabel}
          </div>
        </div>
        <Button size="sm" className="gap-2" onClick={onCreateSuite}>
          <Plus className="size-4" aria-hidden="true" />
          新建
        </Button>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <SearchInput value={suiteQuery} onValueChange={onSuiteQueryChange} placeholder="搜索 Suite…" />
        <Button
          variant="outline"
          size="icon"
          aria-label="刷新 Suites"
          className="size-9"
          onClick={onRefresh}
          disabled={suitesLoading}
        >
          <RefreshCw className={cn('size-4', suitesLoading ? 'animate-spin motion-reduce:animate-none' : '')} aria-hidden="true" />
        </Button>
      </div>

      <div className="mt-3 flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <div className="inline-flex select-none items-center gap-2">
          <Checkbox
            checked={includeArchivedSuites}
            onCheckedChange={(value) => onIncludeArchivedSuitesChange(Boolean(value))}
            aria-label="包含已归档 suites"
          />
          包含已归档
        </div>
        <span className="font-mono tabular-nums">{filteredSuites.length}</span>
      </div>

      {suitesError ? (
        <div className="mt-3 text-xs text-destructive text-pretty">{suitesError}</div>
      ) : null}

      <div className="mt-3">
        <ScrollArea className="h-[420px] pr-2">
          <div className="space-y-2">
            {suitesContent}
          </div>
        </ScrollArea>
      </div>
    </Panel>
  )
}
