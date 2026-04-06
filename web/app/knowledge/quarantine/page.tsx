'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  RefreshCw,
  RotateCcw,
  Settings2,
  ShieldAlert,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { SearchInput } from '@/components/ui/search-input'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

type QuarantineAction = 'release' | 'retry' | 'delete' | 'review' | 'tune'
type ActingState = { id: string; action: QuarantineAction } | null
type ReviewState = 'all' | 'pending' | 'reviewed'

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

function buildReviewAdvice(doc: Document): string[] {
  const reasons = new Set(getDropReasons(doc))
  const advice: string[] = []

  if (reasons.has('outline_only')) advice.push('如果正文有效但被判定为大纲文档，可关闭 outline_only 过滤后重试。')
  if (reasons.has('low_density')) advice.push('如果文本主要由表格或短句构成，可放宽 low_density 阈值后重新入库。')
  if (reasons.has('pii_exceeded')) advice.push('确认是否包含真实敏感信息；若仅为误报，建议先抽样预览再决定放行。')
  if (reasons.has('secrets_exceeded')) advice.push('优先确认命中的内容是否为真实密钥或凭证，再执行放行。')
  if (!advice.length) advice.push('先查看命中规则与原文片段，再决定放行、重试或删除。')

  return advice
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
      <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
        <div className="rounded-full border border-amber-200/70 bg-amber-50 px-3 py-1 text-[11px] font-semibold tracking-[0.08em] text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300">
          暂无记录
        </div>
        <div className="mt-3 text-sm font-semibold text-foreground">当前筛选条件下没有隔离文档</div>
        <div className="mt-1 max-w-md text-xs leading-5 text-muted-foreground">
          可以切换处理状态、命中原因，或搜索其他文档 ID / 文件名继续审核。
        </div>
      </div>
    )
  }

  return (
    <div className="overflow-hidden">
      <div className="hidden gap-4 border-b border-border/60 bg-muted/20 px-5 py-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground lg:grid lg:grid-cols-[minmax(0,2.25fr)_minmax(0,1.25fr)_8.5rem_9rem_9rem]">
        <div>文档</div>
        <div>命中原因</div>
        <div>审核状态</div>
        <div>更新时间</div>
        <div className="text-right">快捷操作</div>
      </div>

      <div className="divide-y divide-border/60">
        {filtered.map((doc) => {
          const active = doc.id === selectedId
          const reasons = getDropReasons(doc)
          const reviewed = isReviewed(doc)
          const busy = acting?.id === doc.id
          const excerpt = doc.error_message?.trim() || (reasons.length ? `命中规则：${reasons.map(reasonLabel).join(' / ')}` : '等待人工审核处理')

          return (
            <div
              key={doc.id}
              role="button"
              tabIndex={0}
              aria-pressed={active}
              onClick={() => onSelect(doc.id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onSelect(doc.id)
                }
              }}
              className={cn(
                'group cursor-pointer transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                active ? 'bg-sky-50/70 dark:bg-sky-500/10' : 'hover:bg-accent/70'
              )}
            >
              <div className="grid gap-4 px-5 py-4 lg:grid-cols-[minmax(0,2.25fr)_minmax(0,1.25fr)_8.5rem_9rem_9rem] lg:items-start">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-xs font-bold text-amber-700 dark:text-amber-300">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      已隔离
                    </span>
                    {reviewed ? (
                      <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-xs font-bold text-emerald-700 dark:text-emerald-300">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        已处理
                      </span>
                    ) : (
                      <span className="inline-flex items-center rounded-full border border-amber-200/70 bg-amber-50 px-2 py-0.5 text-xs font-bold text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300">
                        待审核
                      </span>
                    )}
                    <span className="text-[10px] font-mono text-muted-foreground">ID: {doc.id.slice(0, 8)}</span>
                  </div>
                  <div className="mt-2 truncate font-bold text-foreground">{doc.filename}</div>
                  <div className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{excerpt}</div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] font-medium text-muted-foreground">
                    <span>{formatFileSize(doc.file_size)}</span>
                    <span className="text-muted-foreground/40">·</span>
                    <span>{doc.chunk_count ?? 0} 切片</span>
                  </div>
                </div>

                <div className="min-w-0">
                  {reasons.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {reasons.slice(0, 4).map((reason) => (
                        <Badge
                          key={reason}
                          variant="secondary"
                          className="border border-amber-100 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300"
                        >
                          {reasonLabel(reason)}
                        </Badge>
                      ))}
                      {reasons.length > 4 ? (
                        <Badge variant="secondary" className="border border-border/60 bg-muted text-muted-foreground">
                          +{reasons.length - 4}
                        </Badge>
                      ) : null}
                    </div>
                  ) : (
                    <div className="text-xs text-muted-foreground">未解析到命中原因</div>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-1.5 lg:flex-col lg:items-start">
                  <Badge
                    variant={reviewed ? 'secondary' : 'outline'}
                    className={cn(
                      reviewed
                        ? 'border border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                        : 'border border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300'
                    )}
                  >
                    {reviewed ? '已处理' : '待审核'}
                  </Badge>
                </div>

                <div className="text-sm text-foreground">
                  <div className="font-mono text-[11px] text-muted-foreground">{formatDate(doc.updated_at)}</div>
                </div>

                <div className="flex flex-wrap items-center gap-2 lg:justify-end">
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
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

interface QuarantineDetailPanelProps {
  selected: Document | null
}

function QuarantineDetailPanel({ selected }: Readonly<QuarantineDetailPanelProps>) {
  if (!selected) {
    return null
  }

  return (
    <div className="space-y-5">
      <div className="min-w-0">
        <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">审核摘要</div>
        <div className="mt-2 grid grid-cols-2 gap-3 rounded-2xl border border-border/60 bg-card p-4">
          {[
            { label: '文档 ID', value: selected.id },
            { label: '数据集', value: selected.dataset_id || '-' },
            { label: '文件体积', value: formatFileSize(selected.file_size) },
            { label: '切片数量', value: String(selected.chunk_count ?? 0) },
          ].map((item) => (
            <div key={item.label} className="space-y-1">
              <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{item.label}</div>
              <div className="break-words text-xs font-mono text-foreground">{item.value}</div>
            </div>
          ))}
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

      <div className="rounded-2xl border border-border/60 bg-card p-4">
        <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">处理建议</div>
        <div className="mt-3 space-y-2">
          {buildReviewAdvice(selected).map((tip) => (
            <div key={tip} className="flex items-start gap-2 text-sm text-foreground">
              <div className="mt-1 h-1.5 w-1.5 rounded-full bg-amber-500" />
              <div className="leading-6">{tip}</div>
            </div>
          ))}
        </div>
      </div>

      {getDropReasons(selected).length > 0 ? (
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
      ) : null}
    </div>
  )
}

interface QuarantineReviewDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
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

function QuarantineReviewDrawer({
  open,
  onOpenChange,
  selected,
  acting,
  onRelease,
  onRetry,
  onTune,
  onPreview,
  onShowDetails,
  onMarkReviewed,
  onDelete,
}: Readonly<QuarantineReviewDrawerProps>) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="left-auto right-0 top-0 h-dvh w-[min(520px,100vw)] max-w-[520px] translate-x-0 translate-y-0 rounded-none p-0 overflow-hidden border-l border-border/60 bg-background/95 shadow-strong">
        <DialogHeader className="sr-only">
          <DialogTitle>{selected?.filename || '隔离记录审核'}</DialogTitle>
          <DialogDescription>{selected?.id || ''}</DialogDescription>
        </DialogHeader>

        <div className="flex h-full min-h-0 flex-col bg-background">
          <div className="border-b border-border/60 bg-card px-6 py-5">
            <div className="flex items-start justify-between gap-3 pr-10">
              <div className="min-w-0">
                <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">隔离审核</div>
                <div className="mt-1 truncate text-lg font-bold text-foreground">{selected?.filename || '未选择记录'}</div>
                {selected ? (
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-mono">{selected.id}</span>
                    <span className="text-muted-foreground/40">·</span>
                    <span>{formatDate(selected.updated_at)}</span>
                  </div>
                ) : null}
              </div>
              {selected ? (
                <Badge
                  variant={isReviewed(selected) ? 'secondary' : 'outline'}
                  className={cn(
                    isReviewed(selected)
                      ? 'border border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                      : 'border border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300'
                  )}
                >
                  {isReviewed(selected) ? '已处理' : '待审核'}
                </Badge>
              ) : null}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar">
            <div className="p-6">
              <QuarantineDetailPanel selected={selected} />
            </div>
          </div>

          {selected ? (
            <div className="border-t border-border/60 bg-card/95 px-6 py-4">
              <div className="flex flex-col gap-3">
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
                </div>

                <div className="flex flex-wrap gap-2">
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
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default function QuarantineQueuePage() {
  const { openDocument } = useDocumentView()
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedReason, setSelectedReason] = useState('all')
  const [reviewState, setReviewState] = useState<'all' | 'pending' | 'reviewed'>('pending')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [reviewDrawerOpen, setReviewDrawerOpen] = useState(false)
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
    if (reviewState === 'pending') out = out.filter((d) => !isReviewed(d))
    if (reviewState === 'reviewed') out = out.filter((d) => isReviewed(d))
    if (selectedReason !== 'all') out = out.filter((d) => getDropReasons(d).includes(selectedReason))
    const q = search.trim().toLowerCase()
    if (q) {
      out = out.filter((d) => {
        const filename = (d.filename || '').toLowerCase()
        const id = d.id.toLowerCase()
        return filename.includes(q) || id.includes(q)
      })
    }
    return out
  }, [documents, reviewState, selectedReason, search])

  const listSummary = useMemo(() => {
    if (!documents.length) return null

    const hasSearch = search.trim().length > 0
    const hasReasonFilter = selectedReason !== 'all'

    if (hasSearch || hasReasonFilter) return `筛选 ${filtered.length} / ${documents.length}`
    if (reviewState === 'all') return `共 ${documents.length} 条`
    if (reviewState === 'reviewed') return `${filtered.length} 条已处理`
    return `${filtered.length} 条待审核`
  }, [documents.length, filtered.length, reviewState, search, selectedReason])

  const selected = useMemo(() => {
    if (!selectedId) return null
    return documents.find((d) => d.id === selectedId) || null
  }, [documents, selectedId])

  useEffect(() => {
    if (!selectedId) return
    if (documents.some((doc) => doc.id === selectedId)) return
    setSelectedId(null)
    setReviewDrawerOpen(false)
  }, [documents, selectedId])

  useEffect(() => {
    if (!filtered.length && reviewDrawerOpen) {
      setSelectedId(null)
      setReviewDrawerOpen(false)
    }
  }, [filtered, reviewDrawerOpen])

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
      if (selectedId === doc.id) {
        setSelectedId(null)
        setReviewDrawerOpen(false)
      }
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '删除失败'))
    } finally {
      setActing(null)
    }
  }, [refetch, selectedId])

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
        icon={ShieldAlert}
        iconColor="text-amber-600 dark:text-amber-400"
        size="full"
        topClassName="px-3 md:px-4 xl:px-5 pb-3"
        description={
          <div className="flex flex-wrap items-center gap-2 text-[12px] leading-5 text-muted-foreground">
            <span>聚合命中规则，抽样预览原文，一键放行/重试/删除。</span>
            <span className="inline-flex items-center rounded-md border border-amber-200/70 bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.06em] text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300">
              规则聚合
            </span>
            <span className="inline-flex items-center rounded-md border border-sky-200/70 bg-sky-50 px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.06em] text-sky-700 dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-300">
              原文抽检
            </span>
            <span className="inline-flex items-center rounded-md border border-emerald-200/70 bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.06em] text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300">
              处置闭环
            </span>
          </div>
        }
        actions={
          <>
            <Button
              variant="outline"
              className="group gap-2 rounded-xl bg-background/60"
              onClick={() => refetch()}
            >
              <RefreshCw className={cn('h-3.5 w-3.5', isFetching ? 'animate-spin motion-reduce:animate-none' : '')} />
              刷新
            </Button>
            <div className="flex items-center gap-3 rounded-xl border border-border/60 bg-background/60 px-3.5 py-1.5 shadow-sm transition-colors hover:border-primary/20">
              <span className="text-xs font-bold text-muted-foreground">自动同步</span>
              <Switch checked={autoRefresh} onCheckedChange={setAutoRefresh} className="scale-75 data-[state=checked]:bg-sky-500" />
            </div>
          </>
        }
        top={
          <div className="pt-4">
            <div className="grid gap-3 sm:grid-cols-3">
              {[
                { label: '总隔离', value: stats.total, tone: 'text-foreground', border: 'border-border/60' },
                { label: '待审核', value: stats.unreviewed, tone: 'text-amber-700 dark:text-amber-300', border: 'border-amber-200/80 dark:border-amber-500/20' },
                { label: '已处理', value: stats.reviewed, tone: 'text-emerald-700 dark:text-emerald-300', border: 'border-emerald-200/80 dark:border-emerald-500/20' },
              ].map((item) => (
                <div key={item.label} className={cn('rounded-xl border bg-card/90 px-4 py-3 shadow-soft', item.border)}>
                  <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">{item.label}</div>
                  <div className={cn('mt-2 text-[1.75rem] font-black leading-none tracking-tight', item.tone)}>{item.value}</div>
                </div>
              ))}
            </div>
          </div>
        }
        bodyClassName="px-3 md:px-4 xl:px-5 pb-10 z-10"
      >
        <div className="overflow-hidden rounded-xl border border-border/60 bg-card shadow-soft">
          <div className="border-b border-border/60 px-4 py-3.5">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
              <div className="min-w-0">
                <div className="text-sm font-black text-foreground">审核列表</div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>{documents.length ? '选中后在右侧处置' : '当前空队列'}</span>
                  {listSummary ? (
                    <>
                      <span className="text-muted-foreground/35">·</span>
                      <span className="font-medium text-foreground/75">{listSummary}</span>
                    </>
                  ) : null}
                </div>
              </div>

              <div className="flex w-full flex-col gap-2 xl:w-auto xl:flex-row xl:items-center">
                <SearchInput
                  value={search}
                  onValueChange={setSearch}
                  placeholder="搜索文件名 / 文档 ID"
                  containerClassName="w-full xl:min-w-[18rem]"
                  inputClassName="h-9 rounded-xl border-border/60 bg-background/70 shadow-none"
                />

                <Select value={reviewState} onValueChange={(value) => setReviewState(value as ReviewState)}>
                  <SelectTrigger className="h-9 w-full rounded-xl border-border/60 bg-background/70 shadow-none xl:w-[9.5rem]">
                    <SelectValue placeholder="处理状态" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部记录</SelectItem>
                    <SelectItem value="pending">仅待审核</SelectItem>
                    <SelectItem value="reviewed">仅已处理</SelectItem>
                  </SelectContent>
                </Select>

                <Select value={selectedReason} onValueChange={setSelectedReason}>
                  <SelectTrigger className="h-9 w-full rounded-xl border-border/60 bg-background/70 shadow-none xl:w-[10.5rem]">
                    <SelectValue placeholder="全部原因" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部原因</SelectItem>
                    {sortedReasons.map((reason) => (
                      <SelectItem key={reason} value={reason}>
                        {reasonLabel(reason)} ({reasonCounts[reason] || 0})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          <QuarantineListPanel
            filtered={filtered}
            selectedId={selectedId}
            acting={acting}
            onSelect={(docId) => {
              setSelectedId(docId)
              setReviewDrawerOpen(true)
            }}
            onPreview={openDocument}
            onTune={openTuneDialog}
          />
        </div>
      </PageScaffold>

      <QuarantineReviewDrawer
        open={reviewDrawerOpen}
        onOpenChange={(next) => {
          setReviewDrawerOpen(next)
          if (!next) setSelectedId(null)
        }}
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
                  <div className="text-sm font-bold text-foreground">推荐预设</div>
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
                    onClick={() =>
                      setTunePatch((p) => ({
                        ...p,
                        governance_drop_outline_only: false,
                        governance_drop_low_density: false,
                      }))
                    }
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

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="space-y-3 rounded-xl border border-border bg-card/60 p-4">
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

              <div className="space-y-3 rounded-xl border border-border bg-card/60 p-4">
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

            <div className="space-y-3 rounded-xl border border-border bg-card/60 p-4">
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
