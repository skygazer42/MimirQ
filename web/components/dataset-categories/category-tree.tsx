'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, FolderOpen, FolderPlus, FolderTree, Loader2, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { datasetCategoryApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { queryKeys } from '@/lib/query-keys'

import type { DatasetCategoryCreate, DatasetCategoryNode } from '@/types'

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
            'w-full flex items-center gap-1.5 rounded-[12px] border px-1.5 py-1 text-[11px] transition-all duration-200 active:scale-[0.995]',
            isSelected
              ? 'border-primary/15 bg-primary/10 text-primary shadow-[0_10px_18px_-16px_rgba(37,99,235,0.25)]'
              : 'border-transparent text-muted-foreground hover:border-border/60 hover:bg-muted/40 hover:text-foreground'
          )}
          style={{ paddingLeft: 6 + Math.max(0, Number(node.depth || 0)) * 10 }}
        >
          {hasChildren ? (
            <button
              type="button"
              className="rounded p-0.5 transition-colors duration-200 hover:bg-muted focus-ring"
              aria-label={isExpanded ? '折叠' : '展开'}
              onClick={(e) => {
                e.stopPropagation()
                toggle(node.id)
              }}
            >
              <Chevron className="h-3.5 w-3.5 text-muted-foreground" />
            </button>
          ) : (
            <span className="h-3.5 w-3.5" />
          )}

          <button
            type="button"
            className="focus-ring min-w-0 flex-1 rounded-md px-0.5 py-0.5 text-left"
            onClick={() => onSelect(node.id)}
            title={node.name}
          >
            <span className="flex min-w-0 items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-2">
                <span
                  className={cn(
                    'flex h-5 w-5 shrink-0 items-center justify-center rounded-md border text-muted-foreground',
                    isSelected ? 'border-primary/15 bg-card text-primary shadow-[0_8px_14px_-12px_rgba(37,99,235,0.25)]' : 'border-border/60 bg-muted/50 text-muted-foreground'
                  )}
                >
                  <FolderOpen className="h-3 w-3" />
                </span>
                <span className="truncate text-[11px]" title={node.name}>{node.name}</span>
              </span>
              <span
                className={cn(
                  'rounded-full border px-1.5 py-0.5 tabular-nums text-[9px] font-semibold shadow-sm',
                  isSelected ? 'border-primary/15 bg-card text-primary shadow-[0_8px_14px_-12px_rgba(37,99,235,0.22)]' : 'border-border/60 bg-card text-muted-foreground'
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
    <div className={cn('space-y-0.5', className)}>
      <button
        type="button"
        onClick={() => onSelect(null)}
        className={cn(
          'focus-ring w-full flex items-center justify-between rounded-[12px] border px-2 py-1.5 text-[11px] transition-all duration-200 active:scale-[0.995]',
          selectedId
            ? 'border-transparent text-muted-foreground hover:border-border/60 hover:bg-muted/40 hover:text-foreground'
            : 'border-primary/15 bg-primary/10 text-primary shadow-[0_10px_18px_-16px_rgba(37,99,235,0.25)]'
        )}
      >
        <span className="flex items-center gap-2 min-w-0">
          <span
            className={cn(
              'flex h-5 w-5 shrink-0 items-center justify-center rounded-md border',
              selectedId ? 'border-border/60 bg-muted/50 text-muted-foreground' : 'border-primary/15 bg-card text-primary shadow-[0_8px_14px_-12px_rgba(37,99,235,0.22)]'
            )}
          >
            <FolderTree className="h-3 w-3" />
          </span>
          <span className="truncate text-[11px]" title="全部分类">全部分类</span>
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
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [categoryName, setCategoryName] = useState('')
  const [deleteOpen, setDeleteOpen] = useState(false)

  const categoryTreeQuery = useQuery({
    queryKey: queryKeys.datasetCategories.tree,
    queryFn: () => datasetCategoryApi.listTree(),
  })

  const createCategoryMutation = useMutation({
    mutationFn: (payload: DatasetCategoryCreate) => datasetCategoryApi.create(payload),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.datasetCategories.tree }),
  })

  const deleteCategoryMutation = useMutation({
    mutationFn: (categoryId: string) => datasetCategoryApi.delete(categoryId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.datasetCategories.tree }),
  })

  useEffect(() => {
    if (!categoryTreeQuery.error) return
    reportClientError('Failed to load dataset categories', categoryTreeQuery.error)
    toast.error(formatApiError(categoryTreeQuery.error, '加载分类失败'))
  }, [categoryTreeQuery.error])

  const items = useMemo(() => categoryTreeQuery.data?.items || [], [categoryTreeQuery.data])
  const loading = categoryTreeQuery.isLoading
  const creating = createCategoryMutation.isPending
  const deleting = deleteCategoryMutation.isPending
  const selectedNodeName = useMemo(() => {
    if (!selectedId) return null

    const walk = (nodes: DatasetCategoryNode[]): string | null => {
      for (const node of nodes) {
        if (node.id === selectedId) return node.name
        const childMatch = walk(node.children || [])
        if (childMatch) return childMatch
      }
      return null
    }

    return walk(items)
  }, [items, selectedId])

  const resetCreateState = () => {
    setCategoryName('')
  }

  const handleCreate = async () => {
    const name = categoryName.trim()
    if (!name || creating) return

    try {
      const created = await createCategoryMutation.mutateAsync({
        name,
        parent_id: selectedId || null,
      })
      toast.success(selectedId ? '已创建子分类' : '已创建分类')
      setCreateOpen(false)
      resetCreateState()
      onSelect(created.id)
    } catch (e: unknown) {
      toast.error(formatApiError(e, '创建分类失败'))
    }
  }

  const handleDelete = async () => {
    if (!selectedId || deleting) return

    try {
      await deleteCategoryMutation.mutateAsync(selectedId)
      toast.success('已删除分类')
      setDeleteOpen(false)
      onSelect(null)
    } catch (e: unknown) {
      toast.error(formatApiError(e, '删除分类失败'))
    }
  }

  return (
    <div className={cn('space-y-2.5', className)}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            <FolderTree className="h-3.5 w-3.5 text-primary" />
            <span>目录</span>
          </div>
          <div className="truncate text-[11px] text-muted-foreground" title={selectedNodeName || '全部分类'}>
            {selectedNodeName ? `当前：${selectedNodeName}` : '分类导航'}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <Dialog
            open={createOpen}
            onOpenChange={(open) => {
              setCreateOpen(open)
              if (!open) resetCreateState()
            }}
          >
            <DialogTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 w-8 rounded-full p-0 text-foreground"
                aria-label="新建分类"
                title="新建分类"
              >
                <Plus className="h-3.5 w-3.5" />
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-sm sm:rounded-2xl">
              <DialogHeader>
                <DialogTitle>{selectedId ? '新建子分类' : '新建分类'}</DialogTitle>
                <DialogDescription>
                  {selectedId ? `将在“${selectedNodeName || '当前分类'}”下创建新的子分类。` : '创建一个新的顶级分类，用于组织数据集目录。'}
                </DialogDescription>
              </DialogHeader>

              <div className="grid gap-4 py-1">
                <div className="rounded-2xl border border-border/60 bg-muted/30 px-3 py-2.5 text-xs text-muted-foreground">
                  <div className="flex items-center gap-2">
                    <FolderPlus className="h-3.5 w-3.5 text-primary" />
                    <span>{selectedId ? `父级：${selectedNodeName || '当前分类'}` : '父级：顶级分类'}</span>
                  </div>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="dataset-category-name">分类名称</Label>
                  <Input
                    id="dataset-category-name"
                    value={categoryName}
                    onChange={(e) => setCategoryName(e.target.value)}
                    placeholder="例如：产品文档 / 规范 / 会议纪要"
                    autoFocus
                  />
                </div>
              </div>

              <DialogFooter>
                <Button variant="ghost" onClick={() => setCreateOpen(false)}>取消</Button>
                <Button onClick={handleCreate} disabled={!categoryName.trim() || creating}>
                  {creating ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin motion-reduce:animate-none" /> : <Plus className="mr-1.5 h-4 w-4" />}
                  确认创建
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 rounded-full p-0 text-destructive/60 hover:text-destructive hover:bg-destructive/10"
            onClick={() => setDeleteOpen(true)}
            disabled={!selectedId || deleting}
            aria-label="删除分类"
            title={selectedId ? '删除当前分类' : '请选择分类后删除'}
          >
            {deleting ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <Trash2 className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      <div className="rounded-[1rem] border border-border/60 bg-background/55 p-1.5 shadow-sm">
        {loading && !categoryTreeQuery.data ? (
          <div className="flex items-center gap-2 px-2 py-1 text-xs text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            加载中…
          </div>
        ) : items.length ? (
          <DatasetCategoryTreeView items={items} selectedId={selectedId} onSelect={onSelect} />
        ) : (
          <div className="px-1 py-0.5 text-[11px] text-muted-foreground">
            暂无分类
          </div>
        )}
      </div>

      <AlertDialog
        open={deleteOpen}
        onOpenChange={(open) => {
          if (!deleting) setDeleteOpen(open)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除分类？</AlertDialogTitle>
            <AlertDialogDescription>
              {selectedNodeName ? `将删除分类“${selectedNodeName}”。` : '将删除当前分类。'}
              {' '}如果该分类下仍有子分类，后端会拒绝删除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>取消</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} disabled={deleting}>
              {deleting ? '删除中…' : '删除'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
