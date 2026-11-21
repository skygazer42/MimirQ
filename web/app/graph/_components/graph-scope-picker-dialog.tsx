'use client'

import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Dataset as DatasetIcon, Loader2, Network, Search } from '@/components/icons'
import { useRouter } from '@/i18n/navigation'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { WorkspaceNotice } from '@/components/ui/operational-workspace'
import { datasetApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

type GraphScopePickerDialogProps = Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  currentDatasetId: string | null
  currentPipelineHash: string | null
  currentDocumentCount: number
  onTriggerManualKgUpload: () => void
}>

export function GraphScopePickerDialog({
  open,
  onOpenChange,
  currentDatasetId,
  currentPipelineHash,
  currentDocumentCount,
  onTriggerManualKgUpload,
}: GraphScopePickerDialogProps) {
  const router = useRouter()
  const [query, setQuery] = useState('')
  const [selectedDatasetId, setSelectedDatasetId] = useState(currentDatasetId)
  const wasOpenRef = useRef(false)

  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive(),
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
    enabled: open,
  })
  const datasets = datasetsQuery.data
  const loading = datasetsQuery.isFetching
  const { refetch: refetchDatasets } = datasetsQuery

  useLayoutEffect(() => {
    if (open && !wasOpenRef.current) {
      setSelectedDatasetId(currentDatasetId)
    }
    wasOpenRef.current = open
  }, [currentDatasetId, open])

  const filteredDatasets = useMemo(() => {
    if (datasets === undefined) return undefined
    const needle = query.trim().toLowerCase()
    return datasets
      .filter(
        (dataset) =>
          needle === '' ||
          dataset.name.toLowerCase().includes(needle) ||
          dataset.id.toLowerCase().includes(needle) ||
          dataset.description?.toLowerCase().includes(needle) === true,
      )
      .sort((left, right) => {
        const leftLabel = left.name === '' ? left.id : left.name
        const rightLabel = right.name === '' ? right.id : right.name
        return leftLabel.localeCompare(rightLabel) || left.id.localeCompare(right.id)
      })
  }, [datasets, query])
  const selectedDataset = datasets?.find((dataset) => dataset.id === selectedDatasetId)

  function openSelectedScope() {
    if (selectedDataset === undefined) return
    const params = new URLSearchParams()
    params.set('dataset_id', selectedDataset.id)
    router.push(`/graph?${params.toString()}`)
    onOpenChange(false)
  }

  function resetScope() {
    router.push('/graph')
    onOpenChange(false)
  }

  let currentScopeSummary = '当前未指定图谱范围'
  if (currentDatasetId !== null) {
    currentScopeSummary = `当前已选知识库 ${currentDatasetId}`
  } else if (currentPipelineHash !== null) {
    currentScopeSummary = `当前按解析批次 ${currentPipelineHash} 查看`
  } else if (currentDocumentCount > 0) {
    currentScopeSummary = `当前按 ${currentDocumentCount} 篇文档范围查看`
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] max-w-[42rem] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b border-border/60 px-6 py-5">
          <DialogTitle className="text-base font-semibold text-foreground">选择图谱范围</DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            优先加载已有知识库 KG；外部图谱统一使用 KG JSON / JSONL 导入。
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 space-y-4 overflow-y-auto px-6 py-5">
          <div className="rounded-xl border border-border/60 bg-muted/35 px-4 py-3">
            <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">当前范围</div>
            <div className="mt-1 text-sm text-foreground">{currentScopeSummary}</div>
          </div>

          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search
                aria-hidden="true"
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                type="search"
                aria-label="搜索知识库名称、ID 或说明"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索知识库名称或 ID..."
                className="h-10 rounded-xl border-border/60 bg-background pl-9 shadow-none"
              />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-10 rounded-xl px-3 text-muted-foreground"
              onClick={() => void refetchDatasets()}
              disabled={loading}
            >
              {loading ? (
                <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin motion-reduce:animate-none" />
              ) : null}
              刷新
            </Button>
          </div>

          {datasetsQuery.error !== null ? (
            <WorkspaceNotice retry={() => void refetchDatasets()} retryLabel="重新读取知识库" pending={loading}>
              {datasets === undefined ? null : '更新失败，保留上次目录和当前选择。'}
              {formatApiError(datasetsQuery.error, '知识库目录读取失败')}
            </WorkspaceNotice>
          ) : null}
          {loading && datasets !== undefined ? (
            <p role="status" className="text-sm text-muted-foreground">
              正在更新知识库目录，保留当前选择。
            </p>
          ) : null}
          {selectedDatasetId !== null ? (
            <p role="status" className="text-sm text-muted-foreground">
              待打开范围：{selectedDatasetId}
              {datasets !== undefined && selectedDataset === undefined ? '（当前目录未包含，请重新选择）' : null}
            </p>
          ) : null}
          <div className="rounded-2xl border border-border/60 bg-background/80 p-2">
            <div className="space-y-2 pr-1">
              {filteredDatasets === undefined ? (
                <div role="status" className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
                  {datasetsQuery.isPending ? '正在读取知识库目录…' : '知识库目录暂不可用。'}
                </div>
              ) : filteredDatasets.length === 0 ? (
                <div
                  role="status"
                  className="flex min-h-40 items-center justify-center px-6 text-center text-sm text-muted-foreground"
                >
                  {datasets?.length === 0
                    ? '尚无可选知识库。可以导入 KG JSON / JSONL 创建后端图谱。'
                    : '没有匹配的知识库，请修改或清空搜索。'}
                </div>
              ) : (
                filteredDatasets.map((dataset) => {
                  const isSelected = selectedDatasetId === dataset.id
                  return (
                    <button
                      key={dataset.id}
                      type="button"
                      aria-pressed={isSelected}
                      className={cn(
                        'w-full rounded-xl border px-4 py-3 text-left transition-colors',
                        isSelected
                          ? 'border-primary/40 bg-primary/5 shadow-sm'
                          : 'border-border/50 bg-background hover:border-border hover:bg-muted/40',
                      )}
                      onClick={() => setSelectedDatasetId(dataset.id)}
                    >
                      <div className="flex items-start gap-3">
                        <div
                          className={cn(
                            'mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl',
                            isSelected ? 'bg-primary/12 text-primary' : 'bg-muted/60 text-muted-foreground',
                          )}
                        >
                          <DatasetIcon aria-hidden="true" className="h-4 w-4" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium text-foreground">
                            {dataset.name === '' ? dataset.id : dataset.name}
                          </div>
                          <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{dataset.id}</div>
                          {dataset.description !== undefined && dataset.description !== null ? (
                            <div className="mt-2 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                              {dataset.description}
                            </div>
                          ) : null}
                        </div>
                      </div>
                    </button>
                  )
                })
              )}
            </div>
          </div>
        </div>

        <DialogFooter className="border-t border-border/60 px-6 py-4 sm:justify-between sm:space-x-0">
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center">
            <Button
              type="button"
              className="rounded-xl"
              onClick={() => {
                onOpenChange(false)
                onTriggerManualKgUpload()
              }}
            >
              <Network className="h-4 w-4" />
              导入 KG JSON / JSONL
            </Button>
            <Button type="button" variant="ghost" className="rounded-xl text-muted-foreground" onClick={resetScope}>
              清空范围
            </Button>
          </div>

          <Button
            type="button"
            className="rounded-xl"
            onClick={openSelectedScope}
            disabled={selectedDataset === undefined}
          >
            打开图谱
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
