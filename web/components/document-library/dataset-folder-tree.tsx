'use client'

import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Folder, FolderOpen, Loader2, RefreshCw } from '@/components/icons'
import { useTranslations } from 'next-intl'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { queryKeys } from '@/lib/query-keys'

import type { DocumentFolderNode } from '@/types'

type DatasetFolderTreeViewProps = {
  root: DocumentFolderNode
  selectedPath: string | null
  onSelect: (path: string | null) => void
  labels: {
    collapse: string
    expand: string
    allDirectories: string
  }
}

function DatasetFolderTreeView({ root, selectedPath, onSelect, labels }: Readonly<DatasetFolderTreeViewProps>) {
  const [expandedPaths, setExpandedPaths] = useState(() => new Set(root.children?.map((child) => child.path)))

  const toggle = (path: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const renderNode = (node: DocumentFolderNode) => {
    const children = node.children ?? []
    const hasChildren = children.length > 0
    const isExpanded = hasChildren && expandedPaths.has(node.path)
    const isSelected = selectedPath === node.path
    const depth = Math.max(0, node.depth - 1)

    const Icon = isExpanded ? FolderOpen : Folder
    const Chevron = isExpanded ? ChevronDown : ChevronRight
    let toggleControl = <span className="h-3.5 w-3.5" />
    if (hasChildren) {
      toggleControl = (
        <button
          type="button"
          className="z-10 rounded-sm p-0.5 hover:bg-muted/50 focus-ring"
          aria-label={`${isExpanded ? labels.collapse : labels.expand} ${node.name}`}
          aria-expanded={isExpanded}
          onClick={(e) => {
            e.stopPropagation()
            toggle(node.path)
          }}
        >
          <Chevron className="h-3.5 w-3.5 text-muted-foreground/50 group-hover/node:text-primary transition-colors" />
        </button>
      )
    }

    return (
      <div key={node.path} className="select-none relative">
        <div
          className={cn(
            'w-full flex items-center gap-2 rounded-md border border-transparent px-2 py-1.5 text-sm transition-colors group/node',
            isSelected ? 'border-foreground/10 bg-primary/[0.06] text-primary' : 'hover:bg-muted/40',
          )}
          style={{ paddingLeft: 8 + depth * 12 }}
        >
          {toggleControl}

          <button
            type="button"
            aria-current={isSelected ? true : undefined}
            onClick={() => onSelect(node.path)}
            className="min-w-0 flex-1 flex items-center justify-between gap-2 text-left focus-ring rounded-md py-0.5"
          >
            <span className="min-w-0 flex items-center gap-2">
              <Icon
                className={cn('h-4 w-4 transition-colors', isSelected ? 'text-primary' : 'text-muted-foreground/60')}
              />
              <span className={cn('truncate  transition-colors', isSelected ? 'font-bold' : 'font-medium')}>
                {node.name}
              </span>
            </span>
            <span
              className={cn(
                'font-mono text-[11px] transition-all tabular-nums',
                isSelected ? 'font-semibold' : 'text-muted-foreground/30 font-bold',
              )}
            >
              {node.documents}
            </span>
          </button>
        </div>

        {hasChildren && isExpanded ? (
          <div className="mt-0.5 relative">
            <div
              className="pointer-events-none absolute bottom-2 top-0 w-px bg-foreground/10"
              style={{ left: 15 + depth * 12 }}
            />
            {children.map(renderNode)}
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className="space-y-1">
      <button
        type="button"
        aria-current={selectedPath === null ? true : undefined}
        onClick={() => onSelect(null)}
        className={cn(
          'w-full flex items-center justify-between rounded-md border border-transparent px-2 py-1.5 text-sm transition-colors focus-ring',
          selectedPath ? 'hover:bg-muted/40' : 'border-foreground/10 bg-primary/[0.06] text-primary',
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
  showHeader?: boolean
}

export function DatasetFolderTree({
  datasetId,
  lifecycle = 'active',
  maxDepth = 20,
  selectedPath,
  onSelect,
  className,
  showHeader = true,
}: Readonly<DatasetFolderTreeProps>) {
  const t = useTranslations('DatasetFolderTree')
  const folderTreeParams = useMemo(
    () => ({
      dataset_id: datasetId,
      lifecycle,
      max_depth: maxDepth,
    }),
    [datasetId, lifecycle, maxDepth],
  )

  const folderTreeQuery = useQuery({
    queryKey: queryKeys.documents.folders(folderTreeParams),
    enabled: Boolean(datasetId),
    queryFn: ({ signal }) => documentApi.folders(folderTreeParams, { signal }),
  })

  const tree = datasetId ? (folderTreeQuery.data ?? null) : null
  const loading = Boolean(datasetId) && folderTreeQuery.isLoading
  const refreshing = Boolean(datasetId) && folderTreeQuery.isFetching
  const error = folderTreeQuery.error ? formatApiError(folderTreeQuery.error, t('loadFailed')) : null

  useEffect(() => {
    if (!folderTreeQuery.error) return
    reportClientError('Failed to load dataset folder tree', folderTreeQuery.error)
  }, [folderTreeQuery.error])

  const labels = useMemo(
    () => ({
      collapse: t('collapse'),
      expand: t('expand'),
      allDirectories: t('allDirectories'),
    }),
    [t],
  )

  if (error === null && tree && tree.total_documents > 0 && tree.total_with_source_path <= 0) {
    return null
  }

  let content: ReactNode
  if (loading && !tree) {
    content = (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
        {t('loading')}
      </div>
    )
  } else if (!tree || tree.total_documents <= 0) {
    content = error === null ? <div className="text-xs text-muted-foreground">{t('empty')}</div> : null
  } else {
    content = (
      <DatasetFolderTreeView
        key={JSON.stringify(folderTreeParams)}
        root={tree.root}
        selectedPath={selectedPath}
        onSelect={onSelect}
        labels={labels}
      />
    )
  }

  return (
    <div className={cn('space-y-3', className)}>
      {showHeader ? (
        <div className="flex items-center justify-between gap-2">
          <div className="text-xs font-semibold text-muted-foreground">{t('title')}</div>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-muted-foreground"
            onClick={() => {
              folderTreeQuery.refetch()
            }}
            disabled={refreshing}
            aria-label={t('refresh')}
          >
            {refreshing ? (
              <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
          </Button>
        </div>
      ) : null}

      {error === null ? null : (
        <div role="alert" className="text-xs text-destructive">
          {error}
        </div>
      )}
      {content}
    </div>
  )
}
