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
import { PageHeader } from '@/components/ui/page-header'
import { PageHeaderBar } from '@/components/ui/page-header-bar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import { documentApi } from '@/lib/api-client'
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

type DropReason = string

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

function getDropReasons(doc: Document): DropReason[] {
  const reasons = doc.governance?.drop_reasons || {}
  if (!reasons || typeof reasons !== 'object') return []
  return Object.entries(reasons)
    .filter(([, v]) => typeof v === 'number' && v > 0)
    .map(([k]) => k)
    .sort()
}

function extractTuningOverrides(doc: Document): DocumentPipelineOptions {
  const meta = doc.metadata
  if (!meta || typeof meta !== 'object') return {}
  const pipeline = (meta as any).pipeline
  if (!pipeline || typeof pipeline !== 'object') return {}
  const governance = (pipeline as any).governance
  if (!governance || typeof governance !== 'object') return {}

  const out: DocumentPipelineOptions = {}

  if (typeof governance.drop_outline_only === 'boolean') out.governance_drop_outline_only = governance.drop_outline_only
  if (typeof governance.drop_outline_min_content_chars === 'number') out.governance_drop_outline_min_content_chars = governance.drop_outline_min_content_chars
  if (typeof governance.drop_outline_max_heading_ratio === 'number') out.governance_drop_outline_max_heading_ratio = governance.drop_outline_max_heading_ratio
  if (typeof governance.drop_low_density === 'boolean') out.governance_drop_low_density = governance.drop_low_density
  if (typeof governance.drop_low_density_threshold === 'number') out.governance_drop_low_density_threshold = governance.drop_low_density_threshold
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
    default:
      return reason
  }
}

export default function QuarantineQueuePage() {
  const { openDocument } = useDocumentView()
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedReason, setSelectedReason] = useState<DropReason | 'all'>('all')
  const [hideReviewed, setHideReviewed] = useState(true)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [acting, setActing] = useState<{ id: string; action: 'release' | 'retry' | 'delete' | 'review' | 'tune' } | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailDocumentId, setDetailDocumentId] = useState<string | null>(null)

  const [tuneOpen, setTuneOpen] = useState(false)
  const [tuneTarget, setTuneTarget] = useState<Document | null>(null)
  const [tunePatch, setTunePatch] = useState<DocumentPipelineOptions>({})

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['quarantine-documents'],
    queryFn: async () => {
      const res = await documentApi.list({
        limit: 200,
        status: 'quarantined',
      })
      return res
    },
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
    const patch: Record<string, any> = {
      quarantine_reviewed: true,
      quarantine_reviewed_at: new Date().toISOString(),
      ...(extra || {}),
    }
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
        await documentApi.patchPipeline(doc.id, { patch })
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
    if (!confirm(`确定删除文档「${doc.filename}」吗？此操作不可恢复。`)) return
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
      await documentApi.patchPipeline(doc.id, { patch: tunePatch })
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
      mainClassName="transition-all duration-300 ease-out-expo"
    >
        <PageHeaderBar className="transition-all duration-300">
          <PageHeader
            title="隔离审核队列"
            icon={AlertTriangle}
            iconColor="text-amber-600 dark:text-amber-400"
            className="!pt-6 !pb-6"
            description={
              <span className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
                <span className="font-bold text-slate-700 dark:text-slate-200">QUARANTINE</span>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-100 dark:border-amber-500/20 uppercase tracking-wider">Review</span>
                <span className="text-slate-300 dark:text-slate-600">|</span>
                聚合命中规则，抽样预览原文，一键放行/重试/删除。
              </span>
            }
          >
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                className="gap-2 bg-white/50 dark:bg-slate-900/50 border-slate-200 dark:border-slate-800 hover:bg-white dark:hover:bg-slate-800 hover:border-slate-300 dark:hover:border-slate-700 text-slate-600 dark:text-slate-300 rounded-full transition-all duration-300 shadow-sm"
                onClick={() => refetch()}
              >
                <RefreshCw className={cn('h-3.5 w-3.5 transition-transform', isFetching ? 'animate-spin' : '')} />
                刷新
              </Button>
              <div className="flex items-center gap-3 rounded-full border border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-900/50 backdrop-blur-md px-4 py-1.5 hover:border-slate-300 dark:hover:border-slate-700 transition-colors shadow-sm">
                <span className="text-xs font-bold text-slate-500 dark:text-slate-400">自动同步</span>
                <Switch checked={autoRefresh} onCheckedChange={setAutoRefresh} className="scale-75 data-[state=checked]:bg-sky-500" />
              </div>
            </div>
          </PageHeader>
        </PageHeaderBar>

        <div className="px-8 pt-4 pb-2 flex flex-wrap items-center gap-2">
          <Badge variant="secondary" className="bg-white/70 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800">
            总隔离 {stats.total}
          </Badge>
          <Badge variant="secondary" className="bg-white/70 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800">
            未处理 {stats.unreviewed}
          </Badge>
          <Badge variant="secondary" className="bg-white/70 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800">
            已处理 {stats.reviewed}
          </Badge>
        </div>

        <div className="px-8 pb-4 flex-shrink-0 z-10">
          <div className="flex flex-col lg:flex-row lg:items-center gap-3 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl border border-slate-200 dark:border-slate-800 shadow-lg shadow-slate-200/50 dark:shadow-none rounded-2xl p-3 transition-all duration-300">
            <div className="relative flex-1 group">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 dark:text-slate-500 group-hover:text-sky-500 dark:group-hover:text-sky-400 transition-colors" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索文件名..."
                className="pl-9 bg-transparent border-0 focus-visible:ring-0 text-slate-700 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-600 h-10 rounded-xl"
              />
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-950/40 px-3 py-2">
                <span className="text-xs font-bold text-slate-500 dark:text-slate-400">隐藏已处理</span>
                <Switch checked={hideReviewed} onCheckedChange={setHideReviewed} className="scale-75 data-[state=checked]:bg-amber-500" />
              </div>
            </div>
          </div>
        </div>

        {/* Reason chips */}
        <div className="px-8 pb-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setSelectedReason('all')}
            className={cn(
              'px-3 py-1.5 rounded-full border text-xs font-bold transition-colors',
              selectedReason === 'all'
                ? 'bg-sky-600 text-white border-sky-600'
                : 'bg-white/60 dark:bg-slate-900/60 border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-800'
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
                  ? 'bg-amber-600 text-white border-amber-600'
                  : 'bg-white/60 dark:bg-slate-900/60 border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-800'
              )}
            >
              <span>{reasonLabel(reason)}</span>
              <span className={cn(
                'px-1.5 py-0.5 rounded-full text-[10px] font-black',
                selectedReason === reason ? 'bg-white/20 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300'
              )}>
                {reasonCounts[reason] || 0}
              </span>
            </button>
          ))}
        </div>

        <section className="flex-1 overflow-y-auto px-8 pb-10 z-10 custom-scrollbar">
          <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] gap-4">
            <div className="space-y-2">
              {!filtered.length ? (
                <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/70 dark:bg-slate-900/60 p-10 text-center text-slate-500 dark:text-slate-400">
                  当前筛选条件下没有隔离文档
                </div>
              ) : (
                <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/70 dark:bg-slate-900/60 overflow-hidden">
                  <div className="divide-y divide-slate-200/70 dark:divide-slate-800/70">
                    {filtered.map((doc) => {
                      const active = doc.id === selectedId
                      const reasons = getDropReasons(doc)
                      const reviewed = isReviewed(doc)
                      const busy = acting?.id === doc.id

                      return (
                        <div
                          key={doc.id}
                          role="button"
                          tabIndex={0}
                          onClick={() => setSelectedId(doc.id)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') setSelectedId(doc.id)
                          }}
                          className={cn(
                            'group p-4 flex items-start justify-between gap-4 transition-colors cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400',
                            active
                              ? 'bg-sky-50/70 dark:bg-sky-500/10'
                              : 'hover:bg-slate-50 dark:hover:bg-slate-900'
                          )}
                        >
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300 px-2 py-0.5 text-xs font-bold">
                                <AlertTriangle className="h-3.5 w-3.5" />
                                已隔离
                              </span>
                              {reviewed && (
                                <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 px-2 py-0.5 text-xs font-bold">
                                  <CheckCircle2 className="h-3.5 w-3.5" />
                                  已处理
                                </span>
                              )}
                              <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500">ID: {doc.id.slice(0, 8)}</span>
                            </div>
                            <div className="mt-2 font-bold text-slate-800 dark:text-slate-100 truncate">
                              {doc.filename}
                            </div>
                            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                              <span className="font-mono">{formatDate(doc.updated_at)}</span>
                              <span className="text-slate-300 dark:text-slate-600">·</span>
                              <span>{formatFileSize(doc.file_size)}</span>
                              <span className="text-slate-300 dark:text-slate-600">·</span>
                              <span>{doc.chunk_count ?? 0} 切片</span>
                            </div>
                            {reasons.length > 0 && (
                              <div className="mt-2 flex flex-wrap gap-1.5">
                                {reasons.slice(0, 6).map((r) => (
                                  <Badge
                                    key={r}
                                    variant="secondary"
                                    className="bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-100 dark:border-amber-500/20"
                                  >
                                    {reasonLabel(r)}
                                  </Badge>
                                ))}
                                {reasons.length > 6 && (
                                  <Badge variant="secondary" className="bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
                                    +{reasons.length - 6}
                                  </Badge>
                                )}
                              </div>
                            )}
                          </div>

                          <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-8 px-3 rounded-xl"
                              disabled={busy}
                              onClick={(e) => {
                                e.stopPropagation()
                                openDocument(doc.id)
                              }}
                              title="抽样预览原文"
                            >
                              <Eye className="h-4 w-4 mr-1" />
                              预览
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-8 px-3 rounded-xl"
                              disabled={busy}
                              onClick={(e) => {
                                e.stopPropagation()
                                openTuneDialog(doc)
                              }}
                              title="调参回放"
                            >
                              <Settings2 className="h-4 w-4 mr-1" />
                              调参
                            </Button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/70 dark:bg-slate-900/60 p-5 h-fit">
              {!selected ? (
                <div className="text-sm text-slate-500 dark:text-slate-400">选择一条隔离记录查看详情</div>
              ) : (
                <div className="space-y-4">
                  <div className="min-w-0">
                    <div className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Selected</div>
                    <div className="mt-1 font-bold text-slate-900 dark:text-slate-100 truncate">{selected.filename}</div>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500 dark:text-slate-400">
                      <span className="font-mono">{formatDate(selected.updated_at)}</span>
                      <span>·</span>
                      <span>{formatFileSize(selected.file_size)}</span>
                      <span>·</span>
                      <span>{selected.chunk_count ?? 0} 切片</span>
                    </div>
                  </div>

                  {selected.error_message && (
                    <div className="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50/50 dark:bg-amber-500/10 p-4">
                      <div className="text-xs font-bold text-amber-700 dark:text-amber-300 uppercase tracking-wider">隔离原因</div>
                      <div className="mt-2 text-xs font-mono break-words text-amber-800/80 dark:text-amber-200/80">
                        {selected.error_message}
                      </div>
                    </div>
                  )}

                  {getDropReasons(selected).length > 0 && (
                    <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-950/30 p-4">
                      <div className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">命中规则</div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {getDropReasons(selected).map((r) => (
                          <Badge
                            key={r}
                            variant="secondary"
                            className="bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-100 dark:border-amber-500/20"
                          >
                            {reasonLabel(r)}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      className="rounded-xl bg-amber-600 hover:bg-amber-700 text-white"
                      disabled={acting?.id === selected.id}
                      onClick={() => handleRelease(selected)}
                      title="按命中规则自动关闭对应过滤器，然后重试入库"
                    >
                      <RotateCcw className={cn('h-4 w-4 mr-1', acting?.id === selected.id && acting.action === 'release' ? 'animate-spin' : '')} />
                      放行并重试
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="rounded-xl"
                      disabled={acting?.id === selected.id}
                      onClick={() => handleRetry(selected)}
                    >
                      <RotateCcw className={cn('h-4 w-4 mr-1', acting?.id === selected.id && acting.action === 'retry' ? 'animate-spin' : '')} />
                      直接重试
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="rounded-xl"
                      disabled={acting?.id === selected.id}
                      onClick={() => openTuneDialog(selected)}
                    >
                      <Settings2 className="h-4 w-4 mr-1" />
                      调参回放
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="rounded-xl"
                      disabled={acting?.id === selected.id}
                      onClick={() => openDocument(selected.id)}
                    >
                      <Eye className="h-4 w-4 mr-1" />
                      预览原文
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="rounded-xl"
                      onClick={() => {
                        setDetailDocumentId(selected.id)
                        setDetailOpen(true)
                      }}
                    >
                      <Settings2 className="h-4 w-4 mr-1" />
                      任务详情
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="rounded-xl"
                      disabled={acting?.id === selected.id}
                      onClick={() => handleMarkReviewedOnly(selected)}
                    >
                      <CheckCircle2 className={cn('h-4 w-4 mr-1', acting?.id === selected.id && acting.action === 'review' ? 'animate-spin' : '')} />
                      标记已处理
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      className="rounded-xl"
                      disabled={acting?.id === selected.id}
                      onClick={() => handleDelete(selected)}
                    >
                      <Trash2 className="h-4 w-4 mr-1" />
                      删除
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>

      <IngestionDetailDialog open={detailOpen} onOpenChange={setDetailOpen} documentId={detailDocumentId} />

      <Dialog open={tuneOpen} onOpenChange={(v) => setTuneOpen(v)}>
        <DialogContent className="sm:max-w-[720px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings2 className="h-5 w-5 text-amber-600" />
              调参回放
            </DialogTitle>
            <DialogDescription>
              仅修改该文档的 pipeline overrides（`metadata.pipeline`），用于快速回放重试；不会影响其他文档。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-5">
            <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/30 p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-bold text-slate-900 dark:text-slate-100">
                    推荐预设
                  </div>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
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
              <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-950/30 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-bold">大纲过滤</div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">outline_only</div>
                  </div>
                  <Switch
                    checked={Boolean(tunePatch.governance_drop_outline_only)}
                    onCheckedChange={(v) => setTunePatch((p) => ({ ...p, governance_drop_outline_only: v }))}
                    className="data-[state=checked]:bg-amber-500"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs text-slate-500 dark:text-slate-400">最小内容字符</Label>
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
                    <Label className="text-xs text-slate-500 dark:text-slate-400">标题占比阈值</Label>
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

              <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-950/30 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-bold">低密度过滤</div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">low_density</div>
                  </div>
                  <Switch
                    checked={Boolean(tunePatch.governance_drop_low_density)}
                    onCheckedChange={(v) => setTunePatch((p) => ({ ...p, governance_drop_low_density: v }))}
                    className="data-[state=checked]:bg-amber-500"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-slate-500 dark:text-slate-400">密度阈值</Label>
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

            <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-950/30 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-bold">隔离策略</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">quarantine_on_drop</div>
                </div>
                <Switch
                  checked={Boolean(tunePatch.governance_quarantine_on_drop)}
                  onCheckedChange={(v) => setTunePatch((p) => ({ ...p, governance_quarantine_on_drop: v }))}
                  className="data-[state=checked]:bg-sky-500"
                />
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
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
              <Settings2 className={cn('h-4 w-4 mr-1', acting?.action === 'tune' ? 'animate-spin' : '')} />
              保存配置
            </Button>
            <Button
              type="button"
              className="rounded-xl bg-amber-600 hover:bg-amber-700 text-white"
              onClick={() => saveTune({ retryAfterSave: true })}
              disabled={acting?.action === 'tune'}
            >
              <RotateCcw className={cn('h-4 w-4 mr-1', acting?.action === 'tune' ? 'animate-spin' : '')} />
              保存并重试
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppFrame>
  )
}
