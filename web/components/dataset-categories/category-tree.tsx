'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, FolderOpen, FolderTree, Loader2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { cn, detachPromise } from '@/lib/utils'
import { datasetCategoryApi } from '@/lib/api'
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
            'w-full flex items-center gap-2 rounded-xl px-2 py-1.5 text-sm transition-colors',
            isSelected
              ? 'bg-primary/10 text-primary shadow-sm'
              : 'text-muted-foreground hover:bg-background/80 hover:text-foreground'
          )}
          style={{ paddingLeft: 8 + Math.max(0, Number(node.depth || 0)) * 10 }}
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
            className="focus-ring min-w-0 flex-1 rounded-md px-1 py-0.5 text-left"
            onClick={() => onSelect(node.id)}
          >
            <span className="flex min-w-0 items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-2">
                <span
                  className={cn(
                    'flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border text-muted-foreground',
                    isSelected ? 'border-primary/15 bg-background/90 text-primary' : 'border-border/60 bg-background/70'
                  )}
                >
                  <FolderOpen className="h-3.5 w-3.5" />
                </span>
                <span className="truncate">{node.name}</span>
              </span>
              <span
                className={cn(
                  'rounded-full border px-1.5 py-0.5 tabular-nums text-[10px] shadow-sm',
                  isSelected ? 'border-primary/15 bg-background/85 text-primary' : 'border-border/60 bg-background/85 text-muted-foreground'
                )}
              >
                {Number(node.datasets || 0) || 0}
              </span>
            </span>
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
          'focus-ring w-full flex items-center justify-between rounded-xl px-2 py-2 text-sm transition-colors',
          selectedId
            ? 'text-muted-foreground hover:bg-background/80 hover:text-foreground'
            : 'bg-primary/10 text-primary shadow-sm'
        )}
      >
        <span className="flex items-center gap-2 min-w-0">
          <span
            className={cn(
              'flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border',
              selectedId ? 'border-border/60 bg-background/75 text-muted-foreground' : 'border-primary/15 bg-background/85 text-primary'
            )}
          >
            <FolderTree className="h-3.5 w-3.5" />
          </span>
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
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            <FolderTree className="h-3.5 w-3.5 text-primary" />
            <span>目录导航</span>
          </div>
          <div className="text-xs text-muted-foreground">像文件夹一样筛选数据集目录</div>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 w-8 rounded-full p-0 text-muted-foreground"
          onClick={() => detachPromise(load())}
          disabled={loading}
          aria-label="刷新分类树"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <RefreshCw className="h-4 w-4" />}
        </Button>
      </div>

      <div className="rounded-[1.25rem] border border-border/60 bg-background/55 p-2.5 shadow-sm">
        {loading && !resp ? (
          <div className="flex items-center gap-2 px-2 py-1 text-xs text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            加载中…
          </div>
        ) : items.length ? (
          <DatasetCategoryTreeView items={items} selectedId={selectedId} onSelect={onSelect} />
        ) : (
          <div className="rounded-xl border border-dashed border-border/60 bg-background/70 p-3">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground">
              <span className="flex h-8 w-8 items-center justify-center rounded-xl border border-border/60 bg-card text-muted-foreground">
                <FolderTree className="h-4 w-4" />
              </span>
              暂无分类
            </div>
            <div className="mt-2 text-xs leading-6 text-muted-foreground">
              新建分类后，这里会像文件夹导航一样组织数据集。
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
