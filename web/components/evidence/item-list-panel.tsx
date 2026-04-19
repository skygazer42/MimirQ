'use client'

import { Plus, RefreshCw } from 'lucide-react'

import type { EvidenceItem, EvidenceItemStatus, EvidenceSuite } from '@/types'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

type ItemListPanelProps = {
  selectedSuite: EvidenceSuite | null
  selectedSuiteId: string
  itemQuery: string
  onItemQueryChange: (value: string) => void
  statusFilter: string
  onStatusFilterChange: (value: string) => void
  onRefresh: () => void
  itemsLoading: boolean
  filteredItems: EvidenceItem[]
  itemsError: string | null
  selectedItemId: string
  onCreateItem: () => void
  onSelectItem: (itemId: string) => void
  statusBadgeVariant: (status: EvidenceItemStatus) => 'outline' | 'secondary' | 'soft' | 'destructive'
}

export function ItemListPanel({
  selectedSuite,
  selectedSuiteId,
  itemQuery,
  onItemQueryChange,
  statusFilter,
  onStatusFilterChange,
  onRefresh,
  itemsLoading,
  filteredItems,
  itemsError,
  selectedItemId,
  onCreateItem,
  onSelectItem,
  statusBadgeVariant,
}: Readonly<ItemListPanelProps>) {
  return (
    <Panel className="p-4 lg:col-span-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-foreground">Evidence Items</div>
          <div className="mt-1 text-xs text-muted-foreground text-pretty">
            {selectedSuite ? (
              <>
                Suite：<span className="font-mono">{String(selectedSuite.id).slice(0, 8)}</span> ·{' '}
                <span className="font-medium">{selectedSuite.name}</span>
              </>
            ) : (
              '请选择一个 Suite'
            )}
          </div>
        </div>
        <Button size="sm" className="gap-2" onClick={onCreateItem} disabled={!selectedSuiteId}>
          <Plus className="size-4" aria-hidden="true" />
          新建 Item
        </Button>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-2">
        <SearchInput value={itemQuery} onValueChange={onItemQueryChange} placeholder="搜索 Item…" />
        <div className="flex items-center gap-2">
          <Select
            value={statusFilter}
            onValueChange={(value) => onStatusFilterChange(String(value))}
            disabled={!selectedSuiteId}
          >
            <SelectTrigger className="h-9">
              <SelectValue placeholder="状态筛选" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">全部状态</SelectItem>
              <SelectItem value="draft">draft</SelectItem>
              <SelectItem value="reviewed">reviewed</SelectItem>
              <SelectItem value="approved">approved</SelectItem>
              <SelectItem value="archived">archived</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="icon"
            aria-label="刷新 Items"
            className="size-9"
            onClick={onRefresh}
            disabled={!selectedSuiteId || itemsLoading}
          >
            <RefreshCw className={cn('size-4', itemsLoading ? 'animate-spin motion-reduce:animate-none' : '')} aria-hidden="true" />
          </Button>
          <div className="ml-auto text-xs font-mono tabular-nums text-muted-foreground">
            {filteredItems.length}
          </div>
        </div>
      </div>

      {itemsError ? <div className="mt-3 text-xs text-destructive text-pretty">{itemsError}</div> : null}

      <div className="mt-3">
        <ScrollArea className="h-[420px] pr-2">
          <div className="space-y-2">
            {selectedSuiteId ? (
              itemsLoading ? (
                <div className="text-xs text-muted-foreground">加载中…</div>
              ) : filteredItems.length ? (
                filteredItems.map((item) => {
                  const active = item.id === selectedItemId
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={cn(
                        'w-full rounded-lg border px-3 py-2 text-left transition-colors',
                        active ? 'border-primary/40 bg-primary/5' : 'border-border hover:bg-muted/30'
                      )}
                      onClick={() => onSelectItem(String(item.id))}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="line-clamp-2 text-sm font-medium text-foreground text-pretty">
                            {item.query}
                          </div>
                          {item.notes ? (
                            <div className="mt-1 line-clamp-2 text-xs text-muted-foreground text-pretty">
                              {item.notes}
                            </div>
                          ) : null}
                        </div>
                        <Badge
                          variant={statusBadgeVariant(item.status)}
                          className="font-mono text-[11px] uppercase"
                        >
                          {item.status}
                        </Badge>
                      </div>
                      <div className="mt-2 flex items-center justify-between gap-3 font-mono text-[11px] tabular-nums text-muted-foreground">
                        <span>refs: {Array.isArray(item.reference_sources) ? item.reference_sources.length : 0}</span>
                        <span>{String(item.updated_at || '').slice(0, 19).replaceAll('T', ' ')}</span>
                      </div>
                    </button>
                  )
                })
              ) : (
                <div className="text-xs text-muted-foreground text-pretty">
                  暂无 Items。点击「新建 Item」创建。
                </div>
              )
            ) : (
              <div className="text-xs text-muted-foreground text-pretty">
                选择一个 Suite 后即可查看/创建 Items。
              </div>
            )}
          </div>
        </ScrollArea>
      </div>
    </Panel>
  )
}
