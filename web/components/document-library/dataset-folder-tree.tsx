'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Folder, FolderOpen, Loader2, RefreshCw } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { cn, detachPromise } from '@/lib/utils'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'

import type { DocumentFolderNode, DocumentFolderTreeResponse } from '@/types'

function collectFolderPaths(node: DocumentFolderNode, out: Set<string>) {
  out.add(node.path)
  for (const child of node.children || []) {
    collectFolderPaths(child, out)
  }
}

type DatasetFolderTreeViewProps = {
  root: DocumentFolderNode
  selectedPath: string | null
  onSelect: (path: string | null) => void
  className?: string
  expandAll?: boolean
  labels?: {
    collapse: string
    expand: string
    unnamed: string
    allDirectories: string
  }
}

export function DatasetFolderTreeView({
  root,
  selectedPath,
  onSelect,
  className,
  expandAll = false,
  labels = {
    collapse: '折叠',
    expand: '展开',
    unnamed: '(未命名目录)',
    allDirectories: '全部目录',
  },
}: Readonly<DatasetFolderTreeViewProps>) {
  const initialExpanded = useMemo(() => {
    const next = new Set<string>([''])
    if (expandAll) {
      collectFolderPaths(root, next)
      return next
    }

    // Default: expand root + first level for discoverability.
    for (const child of root.children || []) {
      next.add(child.path)
    }
    return next
  }, [expandAll, root])

  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(initialExpanded)

  // If a new tree is loaded (dataset switch), reset expansion.
  useEffect(() => {
    setExpandedPaths(initialExpanded)
  }, [initialExpanded])

  const toggle = (path: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const renderNode = (node: DocumentFolderNode) => {
    const children = node.children || []
    const hasChildren = children.length > 0
    const isExpanded = hasChildren && expandedPaths.has(node.path)
    const isSelected = (selectedPath || '') === node.path

    const Icon = isExpanded ? FolderOpen : Folder
    const Chevron = isExpanded ? ChevronDown : ChevronRight

    return (
      <div key={node.path} className="select-none">
        <div
          className={cn(
            'w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-colors',
            isSelected ? 'bg-primary/10 text-primary' : 'hover:bg-muted/40'
          )}
          style={{ paddingLeft: 8 + Math.max(0, node.depth - 1) * 12 }}
        >
          {hasChildren ? (
            <button
              type="button"
              className="p-0.5 rounded hover:bg-muted/50 focus-ring"
              aria-label={isExpanded ? labels.collapse : labels.expand}
              onClick={(e) => {
                e.stopPropagation()
                toggle(node.path)
              }}
            >
              <Chevron className="h-4 w-4 text-muted-foreground" />
            </button>
          ) : (
            <span className="h-4 w-4" />
          )}

          <button
            type="button"
            onClick={() => onSelect(node.path || null)}
            className="min-w-0 flex-1 flex items-center justify-between gap-2 text-left focus-ring rounded-md px-1 py-0.5"
          >
            <span className="min-w-0 flex items-center gap-2">
              <Icon className="h-4 w-4 text-muted-foreground" />
              <span className="truncate">{node.name || node.path || labels.unnamed}</span>
            </span>
            <span className="tabular-nums text-xs text-muted-foreground">{node.documents}</span>
          </button>
        </div>

        {hasChildren && isExpanded ? (
          <div className="mt-0.5">
            {children.map(renderNode)}
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
          selectedPath ? 'hover:bg-muted/40' : 'bg-primary/10 text-primary'
        )}
      >
        <span className="flex items-center gap-2 min-w-0">
          <FolderOpen className="h-4 w-4 text-muted-foreground" />
          <span className="truncate">{labels.allDirectories}</span>
        </span>
        <span className="tabular-nums text-xs text-muted-foreground">{root.documents}</span>
      </button>
      {root.children?.length ? root.children.map(renderNode) : null}
    </div>
  )
}

type DatasetFolderTreeProps = {
  datasetId: string
  lifecycle?: 'active' | 'archived' | 'disabled' | 'all'
  maxDepth?: number
  selectedPath: string | null
  onSelect: (path: string | null) => void
  className?: string
}

export function DatasetFolderTree({
  datasetId,
  lifecycle = 'active',
  maxDepth = 20,
  selectedPath,
  onSelect,
  className,
}: Readonly<DatasetFolderTreeProps>) {
  const t = useTranslations('DatasetFolderTree')
  const [tree, setTree] = useState<DocumentFolderTreeResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!datasetId) return
    setLoading(true)
    setError(null)
    try {
      const data = await documentApi.folders({ dataset_id: datasetId, lifecycle, max_depth: maxDepth })
      setTree(data)
    } catch (e: any) {
      console.error('Failed to load dataset folder tree', e)
      setTree(null)
      setError(formatApiError(e, t('loadFailed')))
      toast.error(formatApiError(e, t('loadFailed')))
    } finally {
      setLoading(false)
    }
  }, [datasetId, lifecycle, maxDepth, t])

  useEffect(() => {
    detachPromise(load())
  }, [load])

  const labels = useMemo(
    () => ({
      collapse: t('collapse'),
      expand: t('expand'),
      unnamed: t('unnamed'),
      allDirectories: t('allDirectories'),
    }),
    [t]
  )

  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-semibold text-muted-foreground">{t('title')}</div>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-muted-foreground"
          onClick={() => detachPromise(load())}
          disabled={loading}
          aria-label={t('refresh')}
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <RefreshCw className="h-4 w-4" />}
        </Button>
      </div>

      {(() => {
    if (loading && !tree) {
        return (<div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none"/>
          {t('loading')}
        </div>);
    }
    else if (error) {
            return (<div className="text-xs text-destructive">{error}</div>);
        }
        else if (tree) {
                return (tree.total_with_source_path > 0 ? (<DatasetFolderTreeView root={tree.root} selectedPath={selectedPath} onSelect={onSelect} labels={labels}/>) : (<div className="text-xs text-muted-foreground">{t('emptyWithPath')}</div>));
            }
            else {
                return (<div className="text-xs text-muted-foreground">{t('empty')}</div>);
            }
})()}
    </div>
  )
}
