'use client'

import { useMemo, useState, useSyncExternalStore } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Pencil, RefreshCw, Search, X } from '@/components/icons'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
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
import { datasetApi, datasetCategoryApi } from '@/lib/api/datasets'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { reportClientError } from '@/lib/client-logging'
import { flattenDatasetCategoryTree } from '@/lib/dataset-categories'
import { getCategoryDomainTone } from '@/lib/dataset-domain-tone'
import { queryKeys } from '@/lib/query-keys'
import styles from './category-multi-select.module.css'

function toggleCategoryId(selectedIds: readonly string[], categoryId: string): string[] {
  if (selectedIds.includes(categoryId)) return selectedIds.filter((id) => id !== categoryId)
  return [...selectedIds, categoryId]
}

export function DatasetCategoryMultiSelect({
  datasetId,
  className,
}: Readonly<{ datasetId: string; className?: string }>) {
  const queryClient = useQueryClient()
  const [openedSessionKey, setOpenedSessionKey] = useState<string | null>(null)
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const open = openedSessionKey === sessionKey
  const [draft, setDraft] = useState<string[]>([])
  const [query, setQuery] = useState('')

  const categoryTreeQuery = useQuery({
    queryKey: queryKeys.datasetCategories.tree,
    queryFn: ({ signal }) => datasetCategoryApi.listTree({ signal }),
  })

  const assignedCategoriesQuery = useQuery({
    queryKey: queryKeys.datasets.categories(datasetId),
    queryFn: ({ signal }) => datasetApi.getCategories(datasetId, { signal }),
  })

  const saveCategoriesMutation = useMutation({
    networkMode: 'always',
    mutationFn: (assignment: { datasetId: string; categoryIds: string[]; sessionKey: string }) => {
      if (assignment.sessionKey !== getAuthSessionKey()) throw new Error('当前会话已变化')
      return datasetApi.setCategories(assignment.datasetId, { category_ids: assignment.categoryIds })
    },
    onSuccess: async (result, assignment) => {
      if (assignment.sessionKey !== getAuthSessionKey()) return
      const queryKey = queryKeys.datasets.categories(assignment.datasetId)
      await queryClient.cancelQueries({ queryKey, exact: true })
      if (assignment.sessionKey !== getAuthSessionKey()) return
      queryClient.setQueryData(queryKey, result)
      void queryClient.invalidateQueries({ queryKey: queryKeys.datasets.lists })
    },
  })

  const loadError = categoryTreeQuery.error ?? assignedCategoriesQuery.error
  const assigned = assignedCategoriesQuery.data?.category_ids
  const canEdit = categoryTreeQuery.data !== undefined && assigned !== undefined
  const loading = categoryTreeQuery.isLoading || assignedCategoriesQuery.isLoading
  const refreshing = categoryTreeQuery.isFetching || assignedCategoriesQuery.isFetching
  const saving = saveCategoriesMutation.isPending
  const flat = useMemo(() => flattenDatasetCategoryTree(categoryTreeQuery.data?.items ?? []), [categoryTreeQuery.data])
  const nameById = useMemo(() => new Map(flat.map(({ id, name }) => [id, name])), [flat])

  const filteredFlat = useMemo(() => {
    const searchText = query.trim().toLowerCase()
    if (searchText === '') return flat
    return flat.filter((category) => category.name.toLowerCase().includes(searchText))
  }, [flat, query])

  function changeOpen(nextOpen: boolean) {
    if (saving) return
    if (nextOpen) {
      if (assigned === undefined || categoryTreeQuery.data === undefined) return
      setDraft([...assigned])
      setQuery('')
      setOpenedSessionKey(sessionKey)
      return
    }
    setOpenedSessionKey(null)
  }

  const save = async () => {
    if (!canEdit || saving || openedSessionKey === null) return
    const sessionKey = openedSessionKey
    try {
      await saveCategoriesMutation.mutateAsync({ datasetId, categoryIds: draft, sessionKey })
      if (sessionKey !== getAuthSessionKey()) return
      toast.success('分类已更新')
      setOpenedSessionKey(null)
    } catch (e: unknown) {
      if (sessionKey !== getAuthSessionKey()) return
      reportClientError('Failed to set dataset categories', e)
      toast.error(formatApiError(e, '更新分类失败'))
    }
  }

  return (
    <section className={className} aria-label="数据集分类">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[13px] font-semibold text-foreground">分类</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {(() => {
              if (loading) {
                return (
                  <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
                    加载中…
                  </span>
                )
              }
              if (assigned === undefined) return null
              const visibleCategories = assigned.slice(0, 4)
              const remainingCategoryCount = assigned.length - visibleCategories.length
              if (visibleCategories.length > 0) {
                return (
                  <>
                    {visibleCategories.map((id, index) => (
                      <Badge key={id} variant="soft" className={styles.categoryBadge} data-tone={getCategoryDomainTone(nameById.get(id) ?? id, index)}>
                        {nameById.get(id) ?? id}
                      </Badge>
                    ))}
                    {remainingCategoryCount > 0 ? (
                      <Badge variant="soft" className={styles.categoryBadge}>{`+${remainingCategoryCount}`}</Badge>
                    ) : null}
                  </>
                )
              }
              return <span className="text-xs text-muted-foreground">未设置</span>
            })()}
          </div>
          {loadError !== null ? (
            <p role="alert" className="mt-2 text-sm text-destructive">
              {formatApiError(loadError, '加载分类失败')}
            </p>
          ) : null}
        </div>

        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="size-11 text-muted-foreground sm:size-8"
            onClick={() => {
              void Promise.all([categoryTreeQuery.refetch(), assignedCategoriesQuery.refetch()])
            }}
            disabled={refreshing}
            aria-label="刷新分类"
          >
            {refreshing ? (
              <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            <span className="sr-only">刷新</span>
          </Button>
          <Dialog open={open} onOpenChange={changeOpen}>
            <DialogTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="h-11 gap-1.5 px-2 text-xs text-accent hover:bg-accent/10 hover:text-accent sm:h-8"
                disabled={!canEdit}
              >
                <Pencil className="h-4 w-4" />
                编辑
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-xl">
              <DialogHeader>
                <DialogTitle>编辑分类</DialogTitle>
                <DialogDescription>选择此数据集所属的分类。</DialogDescription>
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
                  <Button variant="secondary" size="sm" className="h-9" onClick={() => setDraft([])} disabled={saving}>
                    清空
                  </Button>
                </div>

                <div className="max-h-[360px] overflow-auto rounded-xl border border-border/60">
                  {filteredFlat.length ? (
                    <div className="divide-y divide-border/60">
                      {filteredFlat.map((category) => (
                        <label
                          key={category.id}
                          className="flex w-full cursor-pointer items-center gap-3 px-3 py-2 transition-colors hover:bg-muted/20"
                        >
                          <Checkbox
                            checked={draft.includes(category.id)}
                            disabled={saving}
                            onCheckedChange={() => setDraft((previous) => toggleCategoryId(previous, category.id))}
                          />
                          <span className="truncate" style={{ paddingLeft: category.depth * 12 }}>
                            {category.name}
                          </span>
                        </label>
                      ))}
                    </div>
                  ) : (
                    <div className="p-6 text-sm text-muted-foreground text-center">暂无分类</div>
                  )}
                </div>
              </div>

              <DialogFooter>
                <Button variant="ghost" onClick={() => setOpenedSessionKey(null)} disabled={saving}>
                  取消
                </Button>
                <Button onClick={() => void save()} disabled={!canEdit || saving}>
                  {saving ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none mr-2" /> : null}
                  保存
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>
    </section>
  )
}
