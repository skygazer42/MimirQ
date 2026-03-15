'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, FolderTree, Loader2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { cn, detachPromise } from '@/lib/utils'
import { datasetCategoryApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'

import type { DatasetCategoryNode, DatasetCategoryTreeResponse } from '@/types'

type DatasetCategoryTreeViewProps = {
  items: DatasetCategoryNode[]
  selectedId: string | null
  onSelect: (categoryId: string | null) => void
  className?: string
  expandAll?: boolean
}

function collectCategoryIds(node: DatasetCategoryNode, out: Set<string>) {
  out.add(node.id)
  for (const child of node.children || []) {
    collectCategoryIds(child, out)
  }
}

export function DatasetCategoryTreeView({
  items,
  selectedId,
  onSelect,
  className,
  expandAll = false,
}: Readonly<DatasetCategoryTreeViewProps>) {
  const initialExpanded = useMemo(() => {
    const next = new Set<string>()
    if (expandAll) {
      for (const n of items) collectCategoryIds(n, next)
      return next
    }
    // Default expand: root level only.
    for (const n of items) next.add(n.id)
    return next
  }, [expandAll, items])

  const [expanded, setExpanded] = useState<Set<string>>(initialExpanded)

  useEffect(() => {
    setExpanded(initialExpanded)
  }, [initialExpanded])

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const renderNode = (node: DatasetCategoryNode) => {
    const hasChildren = (node.children || []).length > 0
    const isExpanded = hasChildren && expanded.has(node.id)
    const isSelected = selectedId === node.id
    const Chevron = isExpanded ? ChevronDown : ChevronRight

    return (
      <div key={node.id} className="select-none">
        <div
          className={cn(
            'w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-colors',
            isSelected ? 'bg-primary/10 text-primary' : 'hover:bg-muted/40'
          )}
          style={{ paddingLeft: 8 + Math.max(0, Number(node.depth || 0)) * 12 }}
        >
          {hasChildren ? (
            <button
              type="button"
              className="p-0.5 rounded hover:bg-muted/50 focus-ring"
              aria-label={isExpanded ? '折叠' : '展开'}
              onClick={(e) => {
                e.stopPropagation()
                toggle(node.id)
              }}
            >
              <Chevron className="h-4 w-4 text-muted-foreground" />
            </button>
          ) : (
            <span className="h-4 w-4" />
          )}

          <button
            type="button"
            className="min-w-0 flex-1 flex items-center justify-between gap-2 text-left focus-ring rounded-md px-1 py-0.5"
            onClick={() => onSelect(node.id)}
          >
            <span className="truncate">{node.name}</span>
            <span className="tabular-nums text-xs text-muted-foreground">{Number(node.datasets || 0) || ''}</span>
          </button>
        </div>

        {hasChildren && isExpanded ? (
          <div className="mt-0.5">
            {(node.children || []).map(renderNode)}
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className={cn('space-y-1', className)}>
      <button
        type="button"
        onClick={() => onSelect(null)}
        className={cn(
          'w-full flex items-center justify-between rounded-lg px-2 py-1.5 text-sm transition-colors focus-ring',
          selectedId ? 'hover:bg-muted/40' : 'bg-primary/10 text-primary'
        )}
      >
        <span className="flex items-center gap-2 min-w-0">
          <FolderTree className="h-4 w-4 text-muted-foreground" />
          <span className="truncate">全部分类</span>
        </span>
      </button>
      {items.map(renderNode)}
    </div>
  )
}

type DatasetCategoryTreeProps = {
  selectedId: string | null
  onSelect: (categoryId: string | null) => void
  className?: string
}

export function DatasetCategoryTree({ selectedId, onSelect, className }: Readonly<DatasetCategoryTreeProps>) {
  const [resp, setResp] = useState<DatasetCategoryTreeResponse | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await datasetCategoryApi.listTree()
      setResp(data)
    } catch (e: any) {
      console.error('Failed to load dataset categories', e)
      toast.error(formatApiError(e, '加载分类失败'))
      setResp(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    detachPromise(load())
  }, [load])

  const items = resp?.items || []

  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-semibold text-muted-foreground">分类</div>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-muted-foreground"
          onClick={() => detachPromise(load())}
          disabled={loading}
          aria-label="刷新分类树"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <RefreshCw className="h-4 w-4" />}
        </Button>
      </div>

      {(() => {
    if (loading && !resp) {
        return (<div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none"/>
          加载中…
        </div>);
    }
    else {
        if (items.length) {
            return (<DatasetCategoryTreeView items={items} selectedId={selectedId} onSelect={onSelect}/>);
        }
        else {
            return (<div className="text-xs text-muted-foreground">暂无分类</div>);
        }
    }
})()}
    </div>
  )
}
