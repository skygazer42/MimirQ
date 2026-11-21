'use client'

import { useMemo, useState, useSyncExternalStore } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronRight,
  FolderOpen,
  FolderPlus,
  FolderTree,
  Loader2,
  Plus,
  Trash2,
} from '@/components/icons'
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { datasetCategoryApi } from '@/lib/api/datasets'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { flattenDatasetCategoryTree } from '@/lib/dataset-categories'
import { queryKeys } from '@/lib/query-keys'

import type { DatasetCategoryCreate, DatasetCategoryNode } from '@/types'

type DatasetCategoryTreeViewProps = {
  items: readonly DatasetCategoryNode[]
  selectedId: string | null
  onSelect: (categoryId: string | null) => void
}

function DatasetCategoryTreeView({ items, selectedId, onSelect }: Readonly<DatasetCategoryTreeViewProps>) {
  const [expanded, setExpanded] = useState<Partial<Record<string, boolean>>>({})

  const renderNode = (node: DatasetCategoryNode, isRoot: boolean) => {
    const children = node.children ?? []
    const hasChildren = children.length > 0
    const isExpanded = hasChildren && (expanded[node.id] ?? isRoot)
    const isSelected = selectedId === node.id
    const Chevron = isExpanded ? ChevronDown : ChevronRight

    return (
      <div key={node.id} className="select-none">
        <div
          className={cn(
            'w-full flex items-center gap-1.5 rounded-[12px] border px-1.5 py-1 text-[11px] transition-all duration-200 active:scale-[0.995]',
            isSelected
              ? 'border-primary/15 bg-primary/10 text-primary shadow-[0_10px_18px_-16px_hsl(var(--primary)/0.25)]'
              : 'border-transparent text-muted-foreground hover:border-border/60 hover:bg-muted/40 hover:text-foreground',
          )}
          style={{ paddingLeft: 6 + node.depth * 10 }}
        >
          {hasChildren ? (
            <button
              type="button"
              className="rounded p-0.5 transition-colors duration-200 hover:bg-muted focus-ring"
              aria-label={isExpanded ? '折叠' : '展开'}
              aria-expanded={isExpanded}
              onClick={() => setExpanded((previous) => ({ ...previous, [node.id]: !isExpanded }))}
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
                    isSelected
                      ? 'border-primary/15 bg-card text-primary shadow-[0_8px_14px_-12px_hsl(var(--primary)/0.25)]'
                      : 'border-border/60 bg-muted/50 text-muted-foreground',
                  )}
                >
                  <FolderOpen className="h-3 w-3" />
                </span>
                <span className="truncate text-[11px]" title={node.name}>
                  {node.name}
                </span>
              </span>
              <span
                className={cn(
                  'rounded-full border px-1.5 py-0.5 tabular-nums text-[9px] font-semibold shadow-sm',
                  isSelected
                    ? 'border-primary/15 bg-card text-primary shadow-[0_8px_14px_-12px_hsl(var(--primary)/0.22)]'
                    : 'border-border/60 bg-card text-muted-foreground',
                )}
              >
                {node.datasets}
              </span>
            </span>
          </button>
        </div>

        {isExpanded ? <div className="mt-0.5">{children.map((child) => renderNode(child, false))}</div> : null}
      </div>
    )
  }

  return (
    <div className="space-y-0.5">
      <button
        type="button"
        onClick={() => onSelect(null)}
        className={cn(
          'focus-ring w-full flex items-center justify-between rounded-[12px] border px-2 py-1.5 text-[11px] transition-all duration-200 active:scale-[0.995]',
          selectedId
            ? 'border-transparent text-muted-foreground hover:border-border/60 hover:bg-muted/40 hover:text-foreground'
            : 'border-primary/15 bg-primary/10 text-primary shadow-[0_10px_18px_-16px_hsl(var(--primary)/0.25)]',
        )}
      >
        <span className="flex items-center gap-2 min-w-0">
          <span
            className={cn(
              'flex h-5 w-5 shrink-0 items-center justify-center rounded-md border',
              selectedId
                ? 'border-border/60 bg-muted/50 text-muted-foreground'
                : 'border-primary/15 bg-card text-primary shadow-[0_8px_14px_-12px_hsl(var(--primary)/0.22)]',
            )}
          >
            <FolderTree className="h-3 w-3" />
          </span>
          <span className="truncate text-[11px]" title="全部分类">
            全部分类
          </span>
        </span>
      </button>
      {items.map((node) => renderNode(node, true))}
    </div>
  )
}

type DatasetCategoryTreeProps = {
  selectedId: string | null
  onSelect: (categoryId: string | null) => void
  className?: string
}

export function DatasetCategoryTree(props: Readonly<DatasetCategoryTreeProps>) {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return <DatasetCategoryTreeContent key={sessionKey} {...props} sessionKey={sessionKey} />
}

function DatasetCategoryTreeContent({
  selectedId,
  onSelect,
  className,
  sessionKey,
}: Readonly<DatasetCategoryTreeProps & { sessionKey: string }>) {
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [categoryName, setCategoryName] = useState('')
  const [categoryToDelete, setCategoryToDelete] = useState<{ id: string; name: string | null } | null>(null)

  const categoryTreeQuery = useQuery({
    queryKey: queryKeys.datasetCategories.tree,
    queryFn: ({ signal }) => datasetCategoryApi.listTree({ signal }),
  })

  function ownsSession() {
    return sessionKey === getAuthSessionKey()
  }

  function refreshCategories() {
    if (ownsSession()) return queryClient.invalidateQueries({ queryKey: queryKeys.datasetCategories.tree })
  }

  const createCategoryMutation = useMutation({
    networkMode: 'always',
    mutationFn: (payload: DatasetCategoryCreate) => {
      if (!ownsSession()) throw new Error('当前会话已变化')
      return datasetCategoryApi.create(payload)
    },
    onSuccess: refreshCategories,
  })

  const deleteCategoryMutation = useMutation({
    networkMode: 'always',
    mutationFn: (categoryId: string) => {
      if (!ownsSession()) throw new Error('当前会话已变化')
      return datasetCategoryApi.delete(categoryId)
    },
    onSuccess: async () => {
      if (!ownsSession()) return
      await Promise.all([
        refreshCategories(),
        queryClient.invalidateQueries({ queryKey: queryKeys.datasets.categoryAssignments }),
        queryClient.invalidateQueries({ queryKey: queryKeys.datasets.lists }),
      ])
    },
  })

  const items = useMemo(() => categoryTreeQuery.data?.items ?? [], [categoryTreeQuery.data])
  const loading = categoryTreeQuery.isLoading
  const creating = createCategoryMutation.isPending
  const deleting = deleteCategoryMutation.isPending
  const selectedNodeName = useMemo(() => {
    if (selectedId === null) return null
    return flattenDatasetCategoryTree(items).find((category) => category.id === selectedId)?.name ?? null
  }, [items, selectedId])

  function changeCreateOpen(open: boolean) {
    if (creating) return
    setCreateOpen(open)
    if (!open) setCategoryName('')
  }

  const handleCreate = async () => {
    const name = categoryName.trim()
    if (!name || creating) return

    try {
      const created = await createCategoryMutation.mutateAsync({
        name,
        parent_id: selectedId,
      })
      if (!ownsSession()) return
      toast.success(selectedId ? '已创建子分类' : '已创建分类')
      setCreateOpen(false)
      setCategoryName('')
      onSelect(created.id)
    } catch (e: unknown) {
      if (!ownsSession()) return
      toast.error(formatApiError(e, '创建分类失败'))
    }
  }

  const handleDelete = async () => {
    if (categoryToDelete === null || deleting) return

    try {
      await deleteCategoryMutation.mutateAsync(categoryToDelete.id)
      if (!ownsSession()) return
      toast.success('已删除分类')
      setCategoryToDelete(null)
      if (selectedId === categoryToDelete.id) onSelect(null)
    } catch (e: unknown) {
      if (!ownsSession()) return
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
          <Dialog open={createOpen} onOpenChange={changeCreateOpen}>
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
                  {selectedId
                    ? `将在“${selectedNodeName || '当前分类'}”下创建新的子分类。`
                    : '创建一个新的顶级分类，用于组织数据集目录。'}
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
                    disabled={creating}
                  />
                </div>
              </div>

              <DialogFooter>
                <Button variant="ghost" onClick={() => changeCreateOpen(false)} disabled={creating}>
                  取消
                </Button>
                <Button onClick={handleCreate} disabled={!categoryName.trim() || creating}>
                  {creating ? (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin motion-reduce:animate-none" />
                  ) : (
                    <Plus className="mr-1.5 h-4 w-4" />
                  )}
                  确认创建
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 rounded-full p-0 text-destructive/60 hover:text-destructive hover:bg-destructive/10"
            onClick={() => {
              if (selectedId) setCategoryToDelete({ id: selectedId, name: selectedNodeName })
            }}
            disabled={!selectedId || deleting}
            aria-label="删除分类"
            title={selectedId ? '删除当前分类' : '请选择分类后删除'}
          >
            {deleting ? (
              <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>

      {categoryTreeQuery.isError ? (
        <div className="flex items-center gap-2 text-xs text-destructive" role="alert">
          <span>{formatApiError(categoryTreeQuery.error, '加载分类失败')}</span>
          <Button
            variant="ghost"
            size="sm"
            disabled={categoryTreeQuery.isFetching}
            onClick={() => void categoryTreeQuery.refetch()}
          >
            重试
          </Button>
        </div>
      ) : null}
      <div className="rounded-[1rem] border border-border/60 bg-background/55 p-1.5 shadow-sm">
        {loading ? (
          <div className="flex items-center gap-2 px-2 py-1 text-xs text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            加载中…
          </div>
        ) : items.length ? (
          <DatasetCategoryTreeView items={items} selectedId={selectedId} onSelect={onSelect} />
        ) : !categoryTreeQuery.isError ? (
          <div className="px-1 py-0.5 text-[11px] text-muted-foreground">暂无分类</div>
        ) : null}
      </div>

      <AlertDialog
        open={categoryToDelete !== null}
        onOpenChange={(open) => {
          if (!open && !deleting) setCategoryToDelete(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除分类？</AlertDialogTitle>
            <AlertDialogDescription>
              {categoryToDelete?.name ? `将删除分类“${categoryToDelete.name}”。` : '将删除当前分类。'}{' '}
              如果该分类下仍有子分类，后端会拒绝删除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={(event) => {
                event.preventDefault()
                void handleDelete()
              }}
              disabled={deleting}
            >
              {deleting ? '删除中…' : '删除'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
