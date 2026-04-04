'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  RefreshCw,
  RotateCcw,
  Search,
  Settings2,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { Panel } from '@/components/ui/panel'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import type { Document, DocumentPipelineOptions } from '@/types'
import { useDocumentView } from '@/store/document-view'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { IngestionDetailDialog } from '@/components/ingestion/ingestion-detail-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'

type QuarantineAction = 'release' | 'retry' | 'delete' | 'review' | 'tune'
type ActingState = { id: string; action: QuarantineAction } | null

function getUserMeta(doc: Document): any {
  const meta = doc.metadata
  if (!meta || typeof meta !== 'object') return null
  const user = (meta as any).user
  return user && typeof user === 'object' ? user : null
}

function isReviewed(doc: Document): boolean {
  const user = getUserMeta(doc)
  return Boolean(user?.quarantine_reviewed)
}

function getDropReasons(doc: Document): string[] {
  const reasons = doc.governance?.drop_reasons || {}
  if (!reasons || typeof reasons !== 'object') return []
  return Object.entries(reasons)
    .filter(([, v]) => typeof v === 'number' && v > 0)
    .map(([k]) => k)
    .sort((a, b) => a.localeCompare(b))
}

function extractTuningOverrides(doc: Document): DocumentPipelineOptions {
  const meta = doc.metadata
  if (!meta || typeof meta !== 'object') return {}
  const pipeline = (meta as any).pipeline
  if (!pipeline || typeof pipeline !== 'object') return {}
  const governance = (pipeline).governance
  if (!governance || typeof governance !== 'object') return {}

  const out: DocumentPipelineOptions = {}

  if (typeof governance.drop_outline_only === 'boolean') out.governance_drop_outline_only = governance.drop_outline_only
  if (typeof governance.drop_outline_min_content_chars === 'number') out.governance_drop_outline_min_content_chars = governance.drop_outline_min_content_chars
  if (typeof governance.drop_outline_max_heading_ratio === 'number') out.governance_drop_outline_max_heading_ratio = governance.drop_outline_max_heading_ratio
  if (typeof governance.drop_low_density === 'boolean') out.governance_drop_low_density = governance.drop_low_density
  if (typeof governance.drop_low_density_threshold === 'number') out.governance_drop_low_density_threshold = governance.drop_low_density_threshold
  if (typeof governance.pii_max_hits === 'number') out.governance_pii_max_hits = governance.pii_max_hits
  if (typeof governance.secrets_max_hits === 'number') out.governance_secrets_max_hits = governance.secrets_max_hits
  if (typeof governance.quarantine_on_drop === 'boolean') out.governance_quarantine_on_drop = governance.quarantine_on_drop

  return out
}

function reasonLabel(reason: string): string {
  switch (reason) {
    case 'outline_only':
      return '大纲文档'
    case 'low_density':
      return '低密度文本'
    case 'empty_document':
      return '空文档'
    case 'pii_exceeded':
      return 'PII 超阈值'
    case 'secrets_exceeded':
      return 'Secrets 超阈值'
    default:
      return reason
  }
}

function createReviewMetadataPatch(extra?: Record<string, any>): Record<string, any> {
  const patch: Record<string, any> = {
    quarantine_reviewed: true,
    quarantine_reviewed_at: new Date().toISOString(),
  }

  if (extra) Object.assign(patch, extra)

  return patch
}

function getBusyIconClassName(acting: ActingState, docId: string, action: QuarantineAction): string {
  return cn(
    'h-4 w-4 mr-1',
    acting?.id === docId && acting.action === action ? 'animate-spin motion-reduce:animate-none' : ''
  )
}

interface QuarantineListPanelProps {
  filtered: Document[]
  selectedId: string | null
  acting: ActingState
  onSelect: (docId: string) => void
  onPreview: (docId: string) => void
  onTune: (doc: Document) => void
}

function QuarantineListPanel({
  filtered,
  selectedId,
  acting,
  onSelect,
  onPreview,
  onTune,
}: Readonly<QuarantineListPanelProps>) {
  if (!filtered.length) {
    return (
      <Panel variant="glass" className="rounded-2xl p-10 text-center text-muted-foreground">
        当前筛选条件下没有隔离文档
      </Panel>
    )
  }

  return (
    <Panel variant="glass" padding="none" className="overflow-hidden rounded-2xl">
      <div className="divide-y divide-border/60">
        {filtered.map((doc) => {
          const active = doc.id === selectedId
          const reasons = getDropReasons(doc)
          const reviewed = isReviewed(doc)
          const busy = acting?.id === doc.id

          return (
            <button
              key={doc.id}
              type="button"
              aria-pressed={active}
              onClick={() => onSelect(doc.id)}
              className={cn(
                'group flex cursor-pointer items-start justify-between gap-4 p-4 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                active ? 'bg-sky-50/70 dark:bg-sky-500/10' : 'hover:bg-accent'
              )}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-xs font-bold text-amber-700 dark:text-amber-300">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    已隔离
                  </span>
                  {reviewed && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-xs font-bold text-emerald-700 dark:text-emerald-300">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      已处理
                    </span>
                  )}
                  <span className="text-[10px] font-mono text-muted-foreground">ID: {doc.id.slice(0, 8)}</span>
                </div>
                <div className="mt-2 truncate font-bold text-foreground">{doc.filename}</div>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-mono">{formatDate(doc.updated_at)}</span>
                  <span className="text-muted-foreground/60">·</span>
                  <span>{formatFileSize(doc.file_size)}</span>
                  <span className="text-muted-foreground/60">·</span>
                  <span>{doc.chunk_count ?? 0} 切片</span>
                </div>
                {reasons.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {reasons.slice(0, 6).map((reason) => (
                      <Badge
                        key={reason}
                        variant="secondary"
                        className="border border-amber-100 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300"
                      >
                        {reasonLabel(reason)}
                      </Badge>
                    ))}
                    {reasons.length > 6 && (
                      <Badge variant="secondary" className="border border-border/60 bg-muted">
                        +{reasons.length - 6}
                      </Badge>
                    )}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 opacity-0 transition-opacity group-hover:opacity-100">
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 rounded-xl px-3"
                  disabled={busy}
                  title="抽样预览原文"
                  onClick={(event) => {
                    event.stopPropagation()
                    onPreview(doc.id)
                  }}
                >
                  <Eye className="mr-1 size-4" />
                  预览
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 rounded-xl px-3"
                  disabled={busy}
                  title="调参回放"
                  onClick={(event) => {
                    event.stopPropagation()
                    onTune(doc)
                  }}
                >
                  <Settings2 className="mr-1 size-4" />
                  调参
                </Button>
              </div>
            </button>
          )
        })}
      </div>
    </Panel>
  )
}

interface QuarantineDetailPanelProps {
  selected: Document | null
  acting: ActingState
  onRelease: (doc: Document) => void
  onRetry: (doc: Document) => void
  onTune: (doc: Document) => void
  onPreview: (docId: string) => void
  onShowDetails: (docId: string) => void
  onMarkReviewed: (doc: Document) => void
  onDelete: (doc: Document) => void
}

function QuarantineDetailPanel({
  selected,
  acting,
  onRelease,
  onRetry,
  onTune,
  onPreview,
  onShowDetails,
  onMarkReviewed,
  onDelete,
}: Readonly<QuarantineDetailPanelProps>) {
  if (!selected) {
    return <div className="text-sm text-muted-foreground">选择一条隔离记录查看详情</div>
  }

  return (
    <div className="space-y-4">
      <div className="min-w-0">
        <div className="text-xs font-bold uppercase text-muted-foreground">Selected</div>
        <div className="mt-1 truncate font-bold text-foreground">{selected.filename}</div>
        <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
          <span className="font-mono">{formatDate(selected.updated_at)}</span>
          <span>·</span>
          <span>{formatFileSize(selected.file_size)}</span>
          <span>·</span>
          <span>{selected.chunk_count ?? 0} 切片</span>
        </div>
      </div>

      {selected.error_message && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-4 dark:border-amber-500/30 dark:bg-amber-500/10">
          <div className="text-xs font-bold uppercase text-amber-700 dark:text-amber-300">隔离原因</div>
          <div className="mt-2 break-words text-xs font-mono text-amber-800/80 dark:text-amber-200/80">
            {selected.error_message}
          </div>
        </div>
      )}

      {getDropReasons(selected).length > 0 && (
        <div className="rounded-xl border border-border bg-muted/30 p-4">
          <div className="text-xs font-bold uppercase text-muted-foreground">命中规则</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {getDropReasons(selected).map((reason) => (
              <Badge
                key={reason}
                variant="secondary"
                className="border border-amber-100 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300"
              >
                {reasonLabel(reason)}
              </Badge>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="warning"
          className="rounded-xl"
          disabled={acting?.id === selected.id}
          title="按命中规则自动关闭对应过滤器，然后重试入库"
          onClick={() => onRelease(selected)}
        >
          <RotateCcw className={getBusyIconClassName(acting, selected.id, 'release')} />
          放行并重试
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="rounded-xl"
          disabled={acting?.id === selected.id}
          onClick={() => onRetry(selected)}
        >
          <RotateCcw className={getBusyIconClassName(acting, selected.id, 'retry')} />
          直接重试
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="rounded-xl"
          disabled={acting?.id === selected.id}
          onClick={() => onTune(selected)}
        >
          <Settings2 className="mr-1 size-4" />
          调参回放
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="rounded-xl"
          disabled={acting?.id === selected.id}
          onClick={() => onPreview(selected.id)}
        >
          <Eye className="mr-1 size-4" />
          预览原文
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="rounded-xl"
          onClick={() => onShowDetails(selected.id)}
        >
          <Settings2 className="mr-1 size-4" />
          任务详情
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="rounded-xl"
          disabled={acting?.id === selected.id}
          onClick={() => onMarkReviewed(selected)}
        >
          <CheckCircle2 className={getBusyIconClassName(acting, selected.id, 'review')} />
          标记已处理
        </Button>
        <ConfirmDialog
          title="删除该文档？"
          description={
            <>
              确定删除文档「<span className="font-mono">{selected.filename}</span>」吗？此操作不可恢复。
            </>
          }
          confirmLabel="删除"
          cancelLabel="返回"
          confirmVariant="destructive"
          confirmDisabled={acting?.id === selected.id}
          onConfirm={() => onDelete(selected)}
        >
          <Button
            size="sm"
            variant="destructive"
            className="rounded-xl"
            disabled={acting?.id === selected.id}
          >
            <Trash2 className="mr-1 size-4" />
            删除
          </Button>
        </ConfirmDialog>
      </div>
    </div>
  )
}

export default function QuarantineQueuePage() {
  const { openDocument } = useDocumentView()
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedReason, setSelectedReason] = useState('all')
  const [hideReviewed, setHideReviewed] = useState(true)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [acting, setActing] = useState<ActingState>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailDocumentId, setDetailDocumentId] = useState<string | null>(null)

  const [tuneOpen, setTuneOpen] = useState(false)
  const [tuneTarget, setTuneTarget] = useState<Document | null>(null)
  const [tunePatch, setTunePatch] = useState<DocumentPipelineOptions>({})

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['quarantine-documents'],
    queryFn: ({ signal }) =>
      documentApi.list(
        {
          limit: 200,
          status: 'quarantined',
        },
        { signal }
      ),
    staleTime: 3_000,
    refetchInterval: autoRefresh ? 5_000 : false,
  })

  const documents = useMemo(() => data?.items || [], [data])

  const reasonCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const doc of documents) {
      const keys = getDropReasons(doc)
      for (const key of keys) {
        counts[key] = (counts[key] || 0) + 1
      }
    }
    return counts
  }, [documents])

  const sortedReasons = useMemo(() => {
    return Object.entries(reasonCounts)
      .sort((a, b) => b[1] - a[1])
      .map(([reason]) => reason)
  }, [reasonCounts])

  const stats = useMemo(() => {
    const total = documents.length
    const reviewed = documents.filter(isReviewed).length
    return {
      total,
      reviewed,
      unreviewed: Math.max(0, total - reviewed),
    }
  }, [documents])

  const filtered = useMemo(() => {
    let out = documents
    if (hideReviewed) out = out.filter((d) => !isReviewed(d))
    if (selectedReason !== 'all') out = out.filter((d) => getDropReasons(d).includes(selectedReason))
    const q = search.trim().toLowerCase()
    if (q) out = out.filter((d) => (d.filename || '').toLowerCase().includes(q))
    return out
  }, [documents, hideReviewed, selectedReason, search])

  const selected = useMemo(() => {
    if (!selectedId) return null
    return filtered.find((d) => d.id === selectedId) || documents.find((d) => d.id === selectedId) || null
  }, [documents, filtered, selectedId])

  useEffect(() => {
    if (!filtered.length) {
      setSelectedId(null)
      return
    }
    if (selectedId && filtered.some((d) => d.id === selectedId)) return
    setSelectedId(filtered[0].id)
  }, [filtered, selectedId])

  const markReviewed = useCallback(async (docId: string, extra?: Record<string, any>) => {
    const patch = createReviewMetadataPatch(extra)
    await documentApi.patchUserMetadata(docId, { patch, replace: false })
  }, [])

  const buildRecommendedPatch = useCallback((doc: Document): DocumentPipelineOptions => {
    const reasons = new Set(getDropReasons(doc))
    const patch: DocumentPipelineOptions = {}
    if (reasons.has('outline_only')) patch.governance_drop_outline_only = false
    if (reasons.has('low_density')) patch.governance_drop_low_density = false
    return patch
  }, [])

  const handleRetry = useCallback(async (doc: Document) => {
    setActing({ id: doc.id, action: 'retry' })
    try {
      await documentApi.retry(doc.id)
      await markReviewed(doc.id, { quarantine_action: 'retry' })
      toast.success('已触发重新入库')
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '重试失败'))
    } finally {
      setActing(null)
    }
  }, [markReviewed, refetch])

  const handleRelease = useCallback(async (doc: Document) => {
    setActing({ id: doc.id, action: 'release' })
    try {
      const patch = buildRecommendedPatch(doc)
      if (Object.keys(patch).length) {
        await documentApi.patchPipeline(doc.id, { patch, replace: false })
      }
      await documentApi.retry(doc.id)
      await markReviewed(doc.id, { quarantine_action: 'release_retry', quarantine_reason: getDropReasons(doc).join(',') })
      toast.success('已放行并重试')
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '放行失败'))
    } finally {
      setActing(null)
    }
  }, [buildRecommendedPatch, markReviewed, refetch])

  const handleDelete = useCallback(async (doc: Document) => {
    setActing({ id: doc.id, action: 'delete' })
    try {
      await documentApi.delete(doc.id)
      toast.success('已删除文档')
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '删除失败'))
    } finally {
      setActing(null)
    }
  }, [refetch])

  const handleMarkReviewedOnly = useCallback(async (doc: Document) => {
    setActing({ id: doc.id, action: 'review' })
    try {
      await markReviewed(doc.id, { quarantine_action: 'reviewed' })
      toast.success('已标记为已处理')
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '标记失败'))
    } finally {
      setActing(null)
    }
  }, [markReviewed, refetch])

  const openTuneDialog = useCallback((doc: Document) => {
    const current = extractTuningOverrides(doc)
    const recommended = buildRecommendedPatch(doc)
    setTuneTarget(doc)
    setTunePatch({ ...current, ...recommended })
    setTuneOpen(true)
  }, [buildRecommendedPatch])

  const saveTune = useCallback(async (opts: { retryAfterSave: boolean }) => {
    if (!tuneTarget) return
    const doc = tuneTarget
    setActing({ id: doc.id, action: 'tune' })
    try {
      await documentApi.patchPipeline(doc.id, { patch: tunePatch, replace: false })
      if (opts.retryAfterSave) {
        await documentApi.retry(doc.id)
        await markReviewed(doc.id, { quarantine_action: 'tune_retry' })
        toast.success('已保存配置并重试')
      } else {
        toast.success('已保存配置')
      }
      setTuneOpen(false)
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '保存失败'))
    } finally {
      setActing(null)
    }
  }, [markReviewed, refetch, tunePatch, tuneTarget])

  return (
    <AppFrame
      rightPanel={<DocumentViewerPanel />}
      withDocumentViewerPadding
    >
      <PageScaffold
        title="隔离审核队列"
        icon={AlertTriangle}
        iconColor="text-amber-600 dark:text-amber-400"
        description={
          <span className="flex items-center gap-2 text-muted-foreground">
            <span className="font-bold text-foreground">QUARANTINE</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-100 dark:border-amber-500/20 uppercase ">
              Review
            </span>
            <span className="text-muted-foreground/60">|</span>
            <span>聚合命中规则，抽样预览原文，一键放行/重试/删除。</span>
          </span>
        }
        actions={
          <>
            <Button
              variant="outline"
              className="group gap-2 rounded-full bg-background/60"
              onClick={() => refetch()}
            >
              <RefreshCw className={cn('h-3.5 w-3.5', isFetching ? 'animate-spin motion-reduce:animate-none' : '')} />
              刷新
            </Button>
	            <div className="flex items-center gap-3 rounded-full border border-border/60 bg-background/60 px-4 py-1.5 hover:border-primary/20 transition-colors shadow-sm">
	              <span className="text-xs font-bold text-muted-foreground">自动同步</span>
	              <Switch checked={autoRefresh} onCheckedChange={setAutoRefresh} className="scale-75 data-[state=checked]:bg-sky-500" />
	            </div>
          </>
        }
        top={
          <div className="pt-4 pb-2 flex flex-wrap items-center gap-2">
            <Badge variant="secondary" className="bg-background/60 border border-border/60">
              总隔离 {stats.total}
            </Badge>
            <Badge variant="secondary" className="bg-background/60 border border-border/60">
              未处理 {stats.unreviewed}
            </Badge>
            <Badge variant="secondary" className="bg-background/60 border border-border/60">
              已处理 {stats.reviewed}
            </Badge>
          </div>
        }
        toolbar={
          <div className="space-y-3">
	            <div className="flex flex-col lg:flex-row lg:items-center gap-3 bg-background/70 border border-border/60 shadow-soft rounded-2xl p-3 transition-colors transition-shadow duration-200 motion-reduce:transition-none hover:shadow-strong hover:border-primary/20">
	              <div className="relative flex-1 group">
	                <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground group-hover:text-sky-500 dark:group-hover:text-sky-400 transition-colors" />
	                <Input
	                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="搜索文件名..."
                  className="pl-9 bg-transparent border-0 text-foreground placeholder:text-muted-foreground h-10 rounded-xl"
                />
              </div>

              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 rounded-xl border border-border/60 bg-background/60 px-3 py-2">
                  <span className="text-xs font-bold text-muted-foreground">隐藏已处理</span>
                  <Switch checked={hideReviewed} onCheckedChange={setHideReviewed} className="scale-75 data-[state=checked]:bg-amber-500" />
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setSelectedReason('all')}
                className={cn(
                  'px-3 py-1.5 rounded-full border text-xs font-bold transition-colors',
                  selectedReason === 'all'
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'bg-background/60 border-border/60 text-muted-foreground hover:bg-accent hover:text-foreground'
                )}
              >
                全部原因
              </button>
              {sortedReasons.map((reason) => (
                <button
                  key={reason}
                  type="button"
                  onClick={() => setSelectedReason(reason)}
                  className={cn(
                    'px-3 py-1.5 rounded-full border text-xs font-bold transition-colors flex items-center gap-2',
                    selectedReason === reason
                      ? 'bg-warning text-warning-foreground border-warning'
                      : 'bg-background/60 border-border/60 text-muted-foreground hover:bg-accent hover:text-foreground'
                  )}
                >
                  <span>{reasonLabel(reason)}</span>
                  <span className={cn(
                    'px-1.5 py-0.5 rounded-full text-[10px] font-black',
                    selectedReason === reason ? 'bg-warning-foreground/10 text-warning-foreground' : 'bg-muted text-muted-foreground'
                  )}>
                    {reasonCounts[reason] || 0}
                  </span>
                </button>
              ))}
            </div>
          </div>
        }
        bodyClassName="pb-10 z-10"
      >
          <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] gap-4">
            <div className="space-y-2">
              <QuarantineListPanel
                filtered={filtered}
                selectedId={selectedId}
                acting={acting}
                onSelect={setSelectedId}
                onPreview={openDocument}
                onTune={openTuneDialog}
              />
            </div>

            <Panel variant="glass" className="rounded-2xl p-5 h-fit">
              <QuarantineDetailPanel
                selected={selected}
                acting={acting}
                onRelease={handleRelease}
                onRetry={handleRetry}
                onTune={openTuneDialog}
                onPreview={openDocument}
                onShowDetails={(docId) => {
                  setDetailDocumentId(docId)
                  setDetailOpen(true)
                }}
                onMarkReviewed={handleMarkReviewedOnly}
                onDelete={handleDelete}
              />
            </Panel>
          </div>
      </PageScaffold>

      <IngestionDetailDialog open={detailOpen} onOpenChange={setDetailOpen} documentId={detailDocumentId} />

      <Dialog open={tuneOpen} onOpenChange={(v) => setTuneOpen(v)}>
        <DialogContent className="sm:max-w-[720px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings2 className="size-5 text-amber-600" />
              调参回放
            </DialogTitle>
            <DialogDescription>
              仅修改该文档的 pipeline overrides（`metadata.pipeline`），用于快速回放重试；不会影响其他文档。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-5">
	            <div className="rounded-xl border border-border bg-muted/40 p-4">
	              <div className="flex items-start justify-between gap-4">
	                <div>
	                  <div className="text-sm font-bold text-foreground">
	                    推荐预设
	                  </div>
	                  <div className="mt-1 text-xs text-muted-foreground">
	                    关闭对应质量过滤器，让更多内容进入切块（仍建议人工抽检）。
	                  </div>
	                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="rounded-xl"
                    onClick={() => setTunePatch((p) => ({ ...p, governance_drop_outline_only: false, governance_drop_low_density: false }))}
                  >
                    关闭质量过滤
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="rounded-xl"
                    onClick={() => {
                      if (!tuneTarget) return
                      const current = extractTuningOverrides(tuneTarget)
                      const recommended = buildRecommendedPatch(tuneTarget)
                      setTunePatch({ ...current, ...recommended })
                    }}
                  >
                    还原推荐
                  </Button>
                </div>
              </div>
	            </div>
	
	            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
	              <div className="rounded-xl border border-border bg-card/60 p-4 space-y-3">
	                <div className="flex items-center justify-between">
	                  <div>
	                    <div className="text-sm font-bold">大纲过滤</div>
	                    <div className="text-xs text-muted-foreground">outline_only</div>
	                  </div>
	                  <Switch
	                    checked={Boolean(tunePatch.governance_drop_outline_only)}
	                    onCheckedChange={(v) => setTunePatch((p) => ({ ...p, governance_drop_outline_only: v }))}
	                    className="data-[state=checked]:bg-warning"
	                  />
	                </div>
	                <div className="grid grid-cols-2 gap-3">
	                  <div className="space-y-1.5">
	                    <Label className="text-xs text-muted-foreground">最小内容字符</Label>
	                    <Input
	                      type="number"
                      min={0}
                      max={200000}
                      value={typeof tunePatch.governance_drop_outline_min_content_chars === 'number' ? tunePatch.governance_drop_outline_min_content_chars : ''}
                      onChange={(e) => {
                        const val = e.target.value === '' ? undefined : Number(e.target.value)
                        setTunePatch((p) => ({ ...p, governance_drop_outline_min_content_chars: Number.isFinite(val as any) ? (val as any) : undefined }))
                      }}
                      className="h-9 rounded-lg"
                    />
	                  </div>
	                  <div className="space-y-1.5">
	                    <Label className="text-xs text-muted-foreground">标题占比阈值</Label>
	                    <Input
	                      type="number"
                      min={0}
                      max={1}
                      step={0.01}
                      value={typeof tunePatch.governance_drop_outline_max_heading_ratio === 'number' ? tunePatch.governance_drop_outline_max_heading_ratio : ''}
                      onChange={(e) => {
                        const raw = e.target.value
                        const val = raw === '' ? undefined : Number(raw)
                        setTunePatch((p) => ({ ...p, governance_drop_outline_max_heading_ratio: Number.isFinite(val as any) ? (val as any) : undefined }))
                      }}
                      className="h-9 rounded-lg"
                    />
	                  </div>
	                </div>
	              </div>
	
	              <div className="rounded-xl border border-border bg-card/60 p-4 space-y-3">
	                <div className="flex items-center justify-between">
	                  <div>
	                    <div className="text-sm font-bold">低密度过滤</div>
	                    <div className="text-xs text-muted-foreground">low_density</div>
	                  </div>
	                  <Switch
	                    checked={Boolean(tunePatch.governance_drop_low_density)}
	                    onCheckedChange={(v) => setTunePatch((p) => ({ ...p, governance_drop_low_density: v }))}
	                    className="data-[state=checked]:bg-warning"
	                  />
	                </div>
	                <div className="space-y-1.5">
	                  <Label className="text-xs text-muted-foreground">密度阈值</Label>
	                  <Input
	                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={typeof tunePatch.governance_drop_low_density_threshold === 'number' ? tunePatch.governance_drop_low_density_threshold : ''}
                    onChange={(e) => {
                      const raw = e.target.value
                      const val = raw === '' ? undefined : Number(raw)
                      setTunePatch((p) => ({ ...p, governance_drop_low_density_threshold: Number.isFinite(val as any) ? (val as any) : undefined }))
                    }}
                    className="h-9 rounded-lg"
                  />
	                </div>
	              </div>
	            </div>
	
	            <div className="rounded-xl border border-border bg-card/60 p-4 space-y-3">
	              <div className="flex items-center justify-between">
	                <div>
	                  <div className="text-sm font-bold">隔离策略</div>
	                  <div className="text-xs text-muted-foreground">quarantine_on_drop</div>
	                </div>
	                <Switch
	                  checked={Boolean(tunePatch.governance_quarantine_on_drop)}
	                  onCheckedChange={(v) => setTunePatch((p) => ({ ...p, governance_quarantine_on_drop: v }))}
	                  className="data-[state=checked]:bg-primary"
	                />
	              </div>
	              <div className="text-xs text-muted-foreground">
	                开启后：触发质量过滤时标记为 quarantined（而非 failed），便于人工复核。
	              </div>
	            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-2">
            <Button
              type="button"
              variant="outline"
              className="rounded-xl"
              onClick={() => setTuneOpen(false)}
              disabled={acting?.action === 'tune'}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="outline"
              className="rounded-xl"
              onClick={() => saveTune({ retryAfterSave: false })}
              disabled={acting?.action === 'tune'}
            >
              <Settings2 className={cn('size-4 mr-1', acting?.action === 'tune' ? 'animate-spin motion-reduce:animate-none' : '')} />
              保存配置
            </Button>
	            <Button
	              type="button"
	              variant="warning"
	              className="rounded-xl"
	              onClick={() => saveTune({ retryAfterSave: true })}
	              disabled={acting?.action === 'tune'}
	            >
              <RotateCcw className={cn('size-4 mr-1', acting?.action === 'tune' ? 'animate-spin motion-reduce:animate-none' : '')} />
              保存并重试
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppFrame>
  )
}
