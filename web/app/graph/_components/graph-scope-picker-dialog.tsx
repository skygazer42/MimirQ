'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Database, Loader2, Network, Search } from 'lucide-react'
import { useRouter } from 'next/navigation'

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
import { datasetApi } from '@/lib/api'
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

const GRAPH_SCOPE_DATASET_PARAMS = { limit: 200 } as const

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
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>(currentDatasetId ?? '')

  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.list(GRAPH_SCOPE_DATASET_PARAMS),
    queryFn: () => datasetApi.list(GRAPH_SCOPE_DATASET_PARAMS),
    enabled: open,
  })
  const datasets = useMemo(
    () => (Array.isArray(datasetsQuery.data?.items) ? datasetsQuery.data.items : []),
    [datasetsQuery.data?.items]
  )
  const loading = datasetsQuery.isFetching
  const error = datasetsQuery.error ? '加载知识库列表失败，请稍后重试。' : null
  const { refetch: refetchDatasets } = datasetsQuery

  useEffect(() => {
    if (!open) return
    setSelectedDatasetId(currentDatasetId ?? '')
  }, [currentDatasetId, open])

  const filteredDatasets = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const items = [...datasets].sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id))
    if (!needle) return items
    return items.filter((dataset) => {
      const name = String(dataset.name || '').toLowerCase()
      const id = String(dataset.id || '').toLowerCase()
      const description = String(dataset.description || '').toLowerCase()
      return name.includes(needle) || id.includes(needle) || description.includes(needle)
    })
  }, [datasets, query])

  const handleOpenSelectedScope = useCallback(() => {
    if (!selectedDatasetId) return
    const params = new URLSearchParams()
    params.set('dataset_id', selectedDatasetId)
    router.push(`/graph?${params.toString()}`)
    onOpenChange(false)
  }, [onOpenChange, router, selectedDatasetId])

  const handleResetScope = useCallback(() => {
    router.push('/graph')
    onOpenChange(false)
  }, [onOpenChange, router])

  let currentScopeSummary = '当前未指定图谱范围'
  if (currentDatasetId) {
    currentScopeSummary = `当前已选知识库 ${currentDatasetId}`
  } else if (currentPipelineHash) {
    currentScopeSummary = `当前按解析批次 ${currentPipelineHash} 查看`
  } else if (currentDocumentCount > 0) {
    currentScopeSummary = `当前按 ${currentDocumentCount} 篇文档范围查看`
  }

  let datasetListContent = filteredDatasets.map((dataset) => {
    const isSelected = selectedDatasetId === dataset.id
    return (
      <button
        key={dataset.id}
        type="button"
        className={cn(
          'w-full rounded-xl border px-4 py-3 text-left transition-colors',
          isSelected ? 'border-primary/40 bg-primary/5 shadow-sm' : 'border-border/50 bg-background hover:border-border hover:bg-muted/40'
        )}
        onClick={() => setSelectedDatasetId(dataset.id)}
      >
        <div className="flex items-start gap-3">
          <div
            className={cn(
              'mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl',
              isSelected ? 'bg-primary/12 text-primary' : 'bg-muted/60 text-muted-foreground'
            )}
          >
            <Database className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-foreground">{dataset.name || dataset.id}</div>
            <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{dataset.id}</div>
            {dataset.description ? (
              <div className="mt-2 line-clamp-2 text-xs leading-relaxed text-muted-foreground">{dataset.description}</div>
            ) : null}
          </div>
        </div>
      </button>
    )
  })
  if (loading && datasets.length === 0) {
    datasetListContent = [
      <div key="loading" className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
        正在读取知识库列表...
      </div>,
    ]
  } else if (error) {
    datasetListContent = [
      <div key="error" className="flex min-h-40 items-center justify-center px-6 text-center text-sm text-muted-foreground">
        {error}
      </div>,
    ]
  } else if (filteredDatasets.length === 0) {
    datasetListContent = [
      <div key="empty" className="flex min-h-40 items-center justify-center px-6 text-center text-sm text-muted-foreground">
        没有匹配的知识库。可尝试清空搜索，或导入 KG JSON / JSONL 创建后端图谱。
      </div>,
    ]
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[42rem] gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b border-border/60 px-6 py-5">
          <DialogTitle className="text-base font-semibold text-foreground">选择图谱范围</DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            优先加载已有知识库 KG；外部图谱统一使用 KG JSON / JSONL 导入。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 px-6 py-5">
          <div className="rounded-xl border border-border/60 bg-muted/35 px-4 py-3">
            <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">当前范围</div>
            <div className="mt-1 text-sm text-foreground">{currentScopeSummary}</div>
          </div>

          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
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
              {loading ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : '刷新'}
            </Button>
          </div>

          <div className="rounded-2xl border border-border/60 bg-background/80 p-2">
            <div className="max-h-[22rem] space-y-2 overflow-auto pr-1">
              {datasetListContent}
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
            <Button
              type="button"
              variant="ghost"
              className="rounded-xl text-muted-foreground"
              onClick={handleResetScope}
            >
              清空范围
            </Button>
          </div>

          <Button
            type="button"
            className="rounded-xl"
            onClick={handleOpenSelectedScope}
            disabled={!selectedDatasetId}
          >
            打开图谱
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
