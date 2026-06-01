'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderTree, Loader2, Pencil, Search, X } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
import { datasetApi, datasetCategoryApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { flattenDatasetCategoryTree } from '@/lib/dataset-categories'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

import type { DatasetCategoryNode } from '@/types'

function toggleId(list: string[], id: string): string[] {
  const exists = list.includes(id)
  if (exists) return list.filter((x) => x !== id)
  return [...list, id]
}

export function DatasetCategoryMultiSelect({ datasetId, className }: Readonly<{ datasetId: string; className?: string }>) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<string[]>([])
  const [query, setQuery] = useState('')

  const categoryTreeQuery = useQuery({
    queryKey: queryKeys.datasetCategories.tree,
    queryFn: () => datasetCategoryApi.listTree(),
  })

  const assignedCategoriesQuery = useQuery({
    queryKey: queryKeys.datasets.categories(datasetId),
    enabled: Boolean(datasetId),
    queryFn: () => datasetApi.getCategories(datasetId),
  })

  const saveCategoriesMutation = useMutation({
    mutationFn: (categoryIds: string[]) =>
      datasetApi.setCategories(datasetId, { category_ids: categoryIds }),
    onSuccess: (res) => {
      queryClient.setQueryData(queryKeys.datasets.categories(datasetId), res)
      queryClient.invalidateQueries({
        queryKey: queryKeys.datasets.categories(datasetId),
      })
    },
  })

  useEffect(() => {
    const error = categoryTreeQuery.error || assignedCategoriesQuery.error
    if (!error) return
    reportClientError('Failed to load dataset categories', error)
    toast.error(formatApiError(error, '加载分类失败'))
  }, [assignedCategoriesQuery.error, categoryTreeQuery.error])

  const tree = useMemo<DatasetCategoryNode[]>(
    () => categoryTreeQuery.data?.items || [],
    [categoryTreeQuery.data]
  )
  const assigned = useMemo(
    () => (assignedCategoriesQuery.data?.category_ids || []).map(String),
    [assignedCategoriesQuery.data]
  )
  const loading = categoryTreeQuery.isLoading || assignedCategoriesQuery.isLoading
  const refreshing = categoryTreeQuery.isFetching || assignedCategoriesQuery.isFetching
  const saving = saveCategoriesMutation.isPending
  const flat = useMemo(() => flattenDatasetCategoryTree(tree), [tree])
  const nameById = useMemo(() => new Map(flat.map((x) => [x.id, x.name])), [flat])

  const assignedBadges = useMemo(() => {
    const names = assigned.map((id) => nameById.get(id) || id)
    const shown = names.slice(0, 4)
    const rest = Math.max(0, names.length - shown.length)
    return { shown, rest }
  }, [assigned, nameById])

  const filteredFlat = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return flat
    return flat.filter((x) => String(x.name || '').toLowerCase().includes(q))
  }, [flat, query])

  const openEditor = () => {
    setDraft([...assigned])
    setQuery('')
    setOpen(true)
  }

  const save = async () => {
    if (!datasetId) return
    try {
      await saveCategoriesMutation.mutateAsync(draft)
      toast.success('分类已更新')
      setOpen(false)
    } catch (e: unknown) {
      reportClientError('Failed to set dataset categories', e)
      toast.error(formatApiError(e, '更新分类失败'))
    }
  }

  return (
    <Panel padding="lg" className={cn('rounded-3xl', className)}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <FolderTree className="h-4 w-4 text-muted-foreground" />
            <div className="text-sm font-semibold text-foreground">分类</div>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {(() => {
    if (loading) {
        return (<span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none"/>
                加载中…
              </span>);
    }
    else if (assignedBadges.shown.length) {
            return (<>
                {assignedBadges.shown.map((name) => (<Badge key={name} variant="outline" className="text-xs">
                    {name}
                  </Badge>))}
                {assignedBadges.rest ? (<Badge variant="soft" className="text-xs">{`+${assignedBadges.rest}`}</Badge>) : null}
              </>);
        }
        else {
            return (<span className="text-xs text-muted-foreground">未设置</span>);
        }
})()}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="h-9 px-3"
            onClick={() => {
              Promise.all([
                categoryTreeQuery.refetch(),
                assignedCategoriesQuery.refetch(),
              ])
            }}
            disabled={refreshing}
            aria-label="刷新分类"
          >
            <Loader2 className={cn('h-4 w-4', refreshing ? 'animate-spin motion-reduce:animate-none' : 'opacity-0')} />
            <span className="sr-only">刷新</span>
          </Button>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" className="h-9 px-3 gap-2" onClick={openEditor} disabled={loading}>
                <Pencil className="h-4 w-4" />
                编辑
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-xl">
              <DialogHeader>
                <DialogTitle>编辑分类</DialogTitle>
                <DialogDescription>为该数据集选择一个或多个分类（用于侧边栏筛选与组织）。</DialogDescription>
              </DialogHeader>

              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <div className="relative flex-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="搜索分类…"
                      className="pl-9"
                    />
                    {query.trim() ? (
                      <button
                        type="button"
                        aria-label="清除搜索"
                        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded hover:bg-muted/40 focus-ring"
                        onClick={() => setQuery('')}
                      >
                        <X className="h-4 w-4 text-muted-foreground" />
                      </button>
                    ) : null}
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="h-9"
                    onClick={() => setDraft([])}
                    disabled={saving}
                  >
                    清空
                  </Button>
                </div>

                <div className="max-h-[360px] overflow-auto rounded-xl border border-border/60">
                  {filteredFlat.length ? (
                    <div className="divide-y divide-border/60">
                      {filteredFlat.map((c) => {
                        const checked = draft.includes(c.id)
                        return (
                          <button
                            key={c.id}
                            type="button"
                            className="w-full flex items-center justify-between gap-3 px-3 py-2 text-left hover:bg-muted/20 transition-colors focus-ring"
                            onClick={() => setDraft((prev) => toggleId(prev, c.id))}
                          >
                            <span className="min-w-0 flex items-center gap-3">
                              <Checkbox checked={checked} onCheckedChange={() => undefined} />
                              <span className="truncate" style={{ paddingLeft: Math.max(0, c.depth) * 12 }}>
                                {c.name}
                              </span>
                            </span>
                          </button>
                        )
                      })}
                    </div>
                  ) : (
                    <div className="p-6 text-sm text-muted-foreground text-center">暂无分类</div>
                  )}
                </div>
              </div>

              <DialogFooter>
                <Button variant="ghost" onClick={() => setOpen(false)} disabled={saving}>
                  取消
                </Button>
                <Button
                  onClick={() => {
                    save()
                  }}
                  disabled={saving}
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none mr-2" /> : null}
                  保存
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>
    </Panel>
  )
}
