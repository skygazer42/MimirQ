/**
 * 文档详情对话框 - 展示最终切片结果
 */
'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Ban, Calendar, CheckCircle2, Copy, Database, Eye, FileText, FileType, Hash, Loader2, Pencil, RefreshCw, Save, Search, Shield, Tags, X } from 'lucide-react'
import { toast } from 'sonner'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { DocumentTags } from '@/components/documents/document-tags'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { StatusBadge, type StatusBadgeStatus } from '@/components/ui/status-badge'
import { TagInput } from '@/components/ui/tag-input'
import { Textarea } from '@/components/ui/textarea'
import { documentApi, kgApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { buildTagsPatch, getUserTagsFromDocument, normalizeTags } from '@/lib/document-user-tags'
import { getParserLabel } from '@/lib/parser-options'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import type {
  Document,
  DocumentAccessInfo,
  DocumentAccessMode,
  DocumentChunk,
  DocumentTimelineItem,
  DocumentTimelineResponse,
  DocumentVersionList,
} from '@/types'

interface DocumentDetailDialogProps {
  document: Document
  trigger?: React.ReactNode
}

const EMPTY_CHUNKS: DocumentChunk[] = []
const ACTIVE_PIPELINE_VALUE = '__active__'
const CHUNK_PAGE_SIZE = 200

function asStatusBadgeStatus(status: string | undefined): StatusBadgeStatus {
  switch (status) {
    case 'pending':
    case 'processing':
    case 'completed':
    case 'failed':
    case 'quarantined':
    case 'cancelled':
      return status
    default:
      return 'pending'
  }
}

function highlightText(text: string, query: string) {
  const needle = query.trim()
  if (!needle) return text

  const haystack = text
  const haystackLower = haystack.toLowerCase()
  const needleLower = needle.toLowerCase()

  const nodes: ReactNode[] = []
  let cursor = 0

  while (cursor < haystack.length) {
    const matchAt = haystackLower.indexOf(needleLower, cursor)
    if (matchAt === -1) {
      nodes.push(haystack.slice(cursor))
      break
    }

    if (matchAt > cursor) {
      nodes.push(haystack.slice(cursor, matchAt))
    }

    const matched = haystack.slice(matchAt, matchAt + needle.length)
    nodes.push(
      <mark key={`${matchAt}-${matched.length}`} className="rounded bg-primary/15 px-0.5 text-foreground">
        {matched}
      </mark>
    )

    cursor = matchAt + needle.length
  }

  return nodes
}

function TraceRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  const display = value?.trim?.() ? value : '-'
  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span
        className={cn("min-w-0 truncate text-foreground", mono ? "font-mono" : null)}
        title={display}
      >
        {display}
      </span>
    </div>
  )
}

export function DocumentDetailDialog({ document: initialDocument, trigger }: DocumentDetailDialogProps) {
  const [open, setOpen] = useState(false)
  const [activeView, setActiveView] = useState<'chunks' | 'timeline'>('chunks')
  const [detail, setDetail] = useState<Document | null>(null)
  const [isLoadingDoc, setIsLoadingDoc] = useState(false)
  const [docError, setDocError] = useState<string | null>(null)

  const scrollParentRef = useRef<HTMLDivElement>(null)

  const [chunks, setChunks] = useState<DocumentChunk[]>(EMPTY_CHUNKS)
  const [chunksTotal, setChunksTotal] = useState(0)
  const [isLoadingChunks, setIsLoadingChunks] = useState(false)
  const [chunkError, setChunkError] = useState<string | null>(null)

  const [timeline, setTimeline] = useState<DocumentTimelineResponse | null>(null)
  const [isLoadingTimeline, setIsLoadingTimeline] = useState(false)
  const [timelineError, setTimelineError] = useState<string | null>(null)

  const [versions, setVersions] = useState<DocumentVersionList | null>(null)
  const [isLoadingVersions, setIsLoadingVersions] = useState(false)
  const [versionsError, setVersionsError] = useState<string | null>(null)
  const [versionsDialogOpen, setVersionsDialogOpen] = useState(false)
  const [isVersionWorking, setIsVersionWorking] = useState(false)
  const [viewPipelineHash, setViewPipelineHash] = useState<string>(ACTIVE_PIPELINE_VALUE)

  const [isKgWorking, setIsKgWorking] = useState(false)
  const [chunkQuery, setChunkQuery] = useState('')
  const [editingChunkId, setEditingChunkId] = useState<string | null>(null)
  const [editingChunkContent, setEditingChunkContent] = useState<string>('')
  const [chunkOpWorkingId, setChunkOpWorkingId] = useState<string | null>(null)
  const [accessInfo, setAccessInfo] = useState<DocumentAccessInfo | null>(null)
  const [accessDialogOpen, setAccessDialogOpen] = useState(false)
  const [accessMode, setAccessMode] = useState<DocumentAccessMode>('inherit')

  const currentTags = useMemo(() => getUserTagsFromDocument(detail || initialDocument), [detail, initialDocument])
  const [tagsEditing, setTagsEditing] = useState(false)
  const [tagsDraft, setTagsDraft] = useState<string[]>([])
  const [tagsError, setTagsError] = useState<string | null>(null)
  const [isSavingTags, setIsSavingTags] = useState(false)

  const canMutateChunks = viewPipelineHash === ACTIVE_PIPELINE_VALUE

  const beginEditChunk = useCallback((chunk: DocumentChunk) => {
    if (!canMutateChunks) return
    setEditingChunkId(chunk.id)
    setEditingChunkContent(String(chunk.content || ''))
  }, [canMutateChunks])

  const cancelEditChunk = useCallback(() => {
    setEditingChunkId(null)
    setEditingChunkContent('')
  }, [])

  const beginEditTags = useCallback(() => {
    setTagsError(null)
    setTagsDraft(currentTags)
    setTagsEditing(true)
  }, [currentTags])

  const cancelEditTags = useCallback(() => {
    setTagsError(null)
    setTagsDraft([])
    setTagsEditing(false)
  }, [])

  const canSaveTags = useMemo(() => {
    if (!tagsEditing) return false
    if (isSavingTags) return false
    const next = normalizeTags(tagsDraft)
    if (next.length !== currentTags.length) return true
    for (let i = 0; i < next.length; i += 1) {
      if (next[i] !== currentTags[i]) return true
    }
    return false
  }, [currentTags, isSavingTags, tagsDraft, tagsEditing])

  const saveEditChunk = useCallback(async () => {
    if (!editingChunkId) return
    if (!canMutateChunks) return
    const chunkId = editingChunkId

    setChunkOpWorkingId(chunkId)
    try {
      const updated = await documentApi.updateChunk(initialDocument.id, chunkId, {
        content: editingChunkContent,
      })
      setChunks((prev) => prev.map((c) => (c.id === chunkId ? updated : c)))
      setEditingChunkId(null)
      setEditingChunkContent('')
      toast.success('已保存切片修改')
    } catch (err) {
      console.error('Update chunk failed:', err)
      toast.error(formatApiError(err, '保存切片失败'))
    } finally {
      setChunkOpWorkingId((prev) => (prev === chunkId ? null : prev))
    }
  }, [canMutateChunks, editingChunkContent, editingChunkId, initialDocument.id])

  const toggleChunkDisabled = useCallback(
    async (chunk: DocumentChunk) => {
      if (!canMutateChunks) return
      setChunkOpWorkingId(chunk.id)
      try {
        const updated = chunk.disabled_at
          ? await documentApi.enableChunk(initialDocument.id, chunk.id)
          : await documentApi.disableChunk(initialDocument.id, chunk.id)
        setChunks((prev) => prev.map((c) => (c.id === chunk.id ? updated : c)))
        toast.success(chunk.disabled_at ? '已启用切片' : '已禁用切片')
      } catch (err) {
        console.error('Toggle chunk disabled failed:', err)
        toast.error(formatApiError(err, '切片操作失败'))
      } finally {
        setChunkOpWorkingId((prev) => (prev === chunk.id ? null : prev))
      }
    },
    [canMutateChunks, initialDocument.id]
  )

  const reembedChunk = useCallback(
    async (chunk: DocumentChunk) => {
      if (!canMutateChunks) return
      setChunkOpWorkingId(chunk.id)
      try {
        const res = await documentApi.reembedChunks(initialDocument.id, { chunk_ids: [chunk.id] })
        toast.success(`已重新嵌入 ${res.reembedded} 个切片`)
      } catch (err) {
        console.error('Re-embed chunk failed:', err)
        toast.error(formatApiError(err, '重新嵌入失败'))
      } finally {
        setChunkOpWorkingId((prev) => (prev === chunk.id ? null : prev))
      }
    },
    [canMutateChunks, initialDocument.id]
  )
  const [accessMembersText, setAccessMembersText] = useState('')
  const [isSavingAccess, setIsSavingAccess] = useState(false)

  const loadDetail = useCallback(async () => {
    setIsLoadingDoc(true)
    setDocError(null)
    try {
      const [data, acl] = await Promise.all([
        documentApi.get(initialDocument.id),
        documentApi.getAccess(initialDocument.id).catch((err) => {
          console.warn('Load document access error:', err)
          return null
        }),
      ])
      setDetail(data)
      setAccessInfo(acl)
    } catch (err: any) {
      console.error('Load document detail error:', err)
      setDocError(formatApiError(err, '获取文档详情失败'))
    } finally {
      setIsLoadingDoc(false)
    }
  }, [initialDocument.id])

  const saveTags = useCallback(async () => {
    if (!canSaveTags) return
    setIsSavingTags(true)
    setTagsError(null)
    try {
      await documentApi.patchUserMetadata(initialDocument.id, buildTagsPatch(tagsDraft))
      toast.success('已更新标签')
      setTagsEditing(false)
      setTagsDraft([])
      await loadDetail()
    } catch (err: any) {
      console.error('Update document tags failed:', err)
      const msg = formatApiError(err, '保存标签失败')
      setTagsError(msg)
      toast.error(msg)
    } finally {
      setIsSavingTags(false)
    }
  }, [canSaveTags, initialDocument.id, loadDetail, tagsDraft])

  const loadVersions = useCallback(async () => {
    setIsLoadingVersions(true)
    setVersionsError(null)
    try {
      const data = await documentApi.listVersions(initialDocument.id)
      setVersions(data)
    } catch (err: any) {
      console.error('Load document versions error:', err)
      setVersionsError(formatApiError(err, '获取文档版本失败'))
    } finally {
      setIsLoadingVersions(false)
    }
  }, [initialDocument.id])

  const loadTimeline = useCallback(async () => {
    setIsLoadingTimeline(true)
    setTimelineError(null)
    try {
      const data = await documentApi.getTimeline(initialDocument.id, { limit: 200 })
      setTimeline(data)
    } catch (err: any) {
      console.error('Load document timeline error:', err)
      setTimelineError(formatApiError(err, '获取文档时间线失败'))
    } finally {
      setIsLoadingTimeline(false)
    }
  }, [initialDocument.id])

  const fetchChunksPage = useCallback(
    async (skip: number) => {
      const q = chunkQuery.trim()
      const pipelineHash = viewPipelineHash === ACTIVE_PIPELINE_VALUE ? undefined : viewPipelineHash
      const res = await documentApi.listChunks(initialDocument.id, {
        skip,
        limit: CHUNK_PAGE_SIZE,
        q: q ? q : undefined,
        pipeline_hash: pipelineHash,
      })
      return res
    },
    [chunkQuery, initialDocument.id, viewPipelineHash]
  )

  const reloadChunks = useCallback(async () => {
    setIsLoadingChunks(true)
    setChunkError(null)
    setChunks([])
    setChunksTotal(0)
    try {
      const res = await fetchChunksPage(0)
      setChunks(res.items || [])
      setChunksTotal(Number(res.total || 0))
    } catch (err: any) {
      console.error('Load document chunks error:', err)
      setChunkError(formatApiError(err, '获取切片失败'))
    } finally {
      setIsLoadingChunks(false)
    }
  }, [fetchChunksPage])

  const loadMoreChunks = useCallback(async () => {
    if (isLoadingChunks) return
    if (chunks.length >= chunksTotal) return
    setIsLoadingChunks(true)
    setChunkError(null)
    try {
      const res = await fetchChunksPage(chunks.length)
      setChunks((prev) => [...prev, ...(res.items || [])])
      setChunksTotal(Number(res.total || 0))
    } catch (err: any) {
      console.error('Load more chunks error:', err)
      setChunkError(formatApiError(err, '加载更多切片失败'))
    } finally {
      setIsLoadingChunks(false)
    }
  }, [chunks.length, chunksTotal, fetchChunksPage, isLoadingChunks])

  useEffect(() => {
    if (!open) return
    setActiveView('chunks')
    void loadDetail()
    void loadVersions()
  }, [open, loadDetail, loadVersions])

  useEffect(() => {
    if (!open) return
    if (activeView !== 'chunks') return
    const handle = window.setTimeout(() => {
      void reloadChunks()
    }, chunkQuery.trim() ? 250 : 0)
    return () => window.clearTimeout(handle)
  }, [open, activeView, chunkQuery, viewPipelineHash, reloadChunks])

  useEffect(() => {
    if (!open) return
    if (activeView !== 'timeline') return
    void loadTimeline()
  }, [open, activeView, loadTimeline])

  const parserBackend =
    (detail?.metadata?.parser_backend as string) || (initialDocument.metadata?.parser_backend as string) || ''
  const chunkStrategy =
    (detail?.metadata?.chunk_strategy as string) || (initialDocument.metadata?.chunk_strategy as string) || ''
  const parserLabel = parserBackend ? getParserLabel(parserBackend) : null
  const chunkStrategyLabel = chunkStrategy ? getChunkStrategyLabel(chunkStrategy) : null

  // 使用详情中的信息优先，否则回退到列表中的简略信息
  const displayDoc = detail || initialDocument
  const status = asStatusBadgeStatus(displayDoc.status)
  const canRunKg = displayDoc.status === 'completed' && !isKgWorking
  const effectiveAccessMode: DocumentAccessMode =
    accessInfo?.mode || (displayDoc.access_mode as DocumentAccessMode | null) || 'inherit'

  const docMeta = (displayDoc.metadata || {}) as any
  const pipeline = (displayDoc as any)?.pipeline || null
  const pipelineEffective = (pipeline?.pipeline_effective || docMeta.pipeline_effective || {}) as any
  const analyticsRaw = (pipeline?.analytics_raw || docMeta.document_analytics_raw || {}) as any
  const governanceRulePacks: string[] = Array.isArray(pipeline?.governance_rule_packs)
    ? pipeline.governance_rule_packs
    : Array.isArray(docMeta.governance_rule_packs)
      ? docMeta.governance_rule_packs
      : []

  const activePipelineHash =
    String(
      pipeline?.active_pipeline_hash ||
        versions?.active_pipeline_hash ||
        docMeta.active_pipeline_hash ||
        docMeta.pipeline_hash ||
        ''
    ).trim() || ''
  const lastPipelineHash = String(pipeline?.pipeline_hash || docMeta.pipeline_hash || '').trim() || ''
  const viewingPipelineHash = viewPipelineHash === ACTIVE_PIPELINE_VALUE ? activePipelineHash : viewPipelineHash

  const accessModeLabel = useMemo(() => {
    switch (effectiveAccessMode) {
      case 'inherit':
        return '继承数据集'
      case 'only_me':
        return '仅我可见'
      case 'partial_members':
        return '指定成员'
      case 'all_team_members':
        return '团队成员'
      default:
        return String(effectiveAccessMode)
    }
  }, [effectiveAccessMode])

  const isSearching = chunkQuery.trim().length > 0
  const canLoadMoreChunks = chunks.length < chunksTotal
  const loadError = docError || chunkError
  const timelineItems: DocumentTimelineItem[] = timeline?.items || []
  const timelineTotal = Number(timeline?.total || timelineItems.length)

  // eslint-disable-next-line react-hooks/incompatible-library
  const chunkRowVirtualizer = useVirtualizer({
    count: activeView === 'chunks' ? chunks.length : 0,
    getScrollElement: () => scrollParentRef.current,
    estimateSize: () => 220,
    overscan: 8,
    getItemKey: (idx) => chunks[idx]?.id ?? idx,
  })

  // eslint-disable-next-line react-hooks/incompatible-library
  const timelineRowVirtualizer = useVirtualizer({
    count: activeView === 'timeline' ? timelineItems.length : 0,
    getScrollElement: () => scrollParentRef.current,
    estimateSize: () => 160,
    overscan: 8,
    getItemKey: (idx) => timelineItems[idx]?.id ?? idx,
  })

  const copyToClipboard = useCallback(async (text: string) => {
    const content = text || ''
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(content)
      } else {
        const textarea = window.document.createElement('textarea')
        textarea.value = content
        textarea.style.position = 'fixed'
        textarea.style.left = '0'
        textarea.style.top = '0'
        textarea.style.opacity = '0'
        window.document.body.appendChild(textarea)
        textarea.focus()
        textarea.select()
        const ok = window.document.execCommand('copy')
        window.document.body.removeChild(textarea)
        if (!ok) throw new Error('copy failed')
      }
      toast.success('已复制到剪贴板')
    } catch (err) {
      console.error('Copy failed:', err)
      toast.error('复制失败')
    }
  }, [])

  const handleActivateVersion = useCallback(
    async (pipelineHash: string) => {
      const ph = String(pipelineHash || '').trim()
      if (!ph) return

      setIsVersionWorking(true)
      try {
        await documentApi.activateVersion(initialDocument.id, ph)
        toast.success('已切换激活版本')
        setViewPipelineHash(ACTIVE_PIPELINE_VALUE)
        await Promise.all([loadDetail(), loadVersions()])
        await reloadChunks()
      } catch (err: any) {
        console.error('Activate document version failed:', err)
        toast.error(formatApiError(err, '切换版本失败'))
      } finally {
        setIsVersionWorking(false)
      }
    },
    [initialDocument.id, loadDetail, loadVersions, reloadChunks]
  )

  const handleDeleteVersion = useCallback(
    async (pipelineHash: string) => {
      const ph = String(pipelineHash || '').trim()
      if (!ph) return

      setIsVersionWorking(true)
      try {
        await documentApi.deleteVersion(initialDocument.id, ph)
        toast.success('已删除版本')
        // If the user was viewing this version, fallback to active.
        if (viewPipelineHash === ph) {
          setViewPipelineHash(ACTIVE_PIPELINE_VALUE)
        }
        await loadVersions()
        await loadDetail()
        await reloadChunks()
      } catch (err: any) {
        console.error('Delete document version failed:', err)
        toast.error(formatApiError(err, '删除版本失败'))
      } finally {
        setIsVersionWorking(false)
      }
    },
    [initialDocument.id, loadDetail, loadVersions, reloadChunks, viewPipelineHash]
  )

  const handleExtractKG = async () => {
    if (!canRunKg) return
    setIsKgWorking(true)
    try {
      await kgApi.extract(displayDoc.id, { async: true, replace_existing: true, prune_orphan_entities: true })
      toast.success('已提交 KG 抽取任务（可前往图谱页刷新查看）')
    } catch (err: any) {
      console.error('KG extract failed:', err)
      toast.error(err?.message || 'KG 抽取失败')
    } finally {
      setIsKgWorking(false)
    }
  }

  const handleDeleteKG = async () => {
    if (isKgWorking) return
    setIsKgWorking(true)
    try {
      const res = await kgApi.deleteDocumentKG(displayDoc.id, { prune_orphan_entities: true })
      toast.success(`已删除 KG 事件 ${res.events_deleted}，清理实体 ${res.entities_pruned}`)
    } catch (err: any) {
      console.error('KG delete failed:', err)
      toast.error(err?.message || '删除 KG 失败')
    } finally {
      setIsKgWorking(false)
    }
  }

  const parseAccessMembers = useCallback((raw: string): string[] => {
    const parts = (raw || '')
      .split(/[\n,;]+/g)
      .map((s) => s.trim())
      .filter(Boolean)
    const out: string[] = []
    const seen = new Set<string>()
    for (const p of parts) {
      if (seen.has(p)) continue
      seen.add(p)
      out.push(p)
      if (out.length >= 200) break
    }
    return out
  }, [])

  const handleSaveAccess = useCallback(async () => {
    if (!displayDoc?.id) return
    setIsSavingAccess(true)
    try {
      const payload = {
        mode: accessMode,
        partial_member_list: accessMode === 'partial_members' ? parseAccessMembers(accessMembersText) : null,
      }
      const res = await documentApi.updateAccess(displayDoc.id, payload)
      setAccessInfo(res)
      setDetail((prev) =>
        prev
          ? {
              ...prev,
              access_mode: res.mode === 'inherit' ? null : res.mode,
              owner_id: res.owner_id ?? prev.owner_id,
            }
          : prev
      )
      toast.success('已更新文档访问控制')
      setAccessDialogOpen(false)
    } catch (err: any) {
      console.error('Update document access failed:', err)
      toast.error(formatApiError(err, '更新访问控制失败'))
    } finally {
      setIsSavingAccess(false)
    }
  }, [accessMode, accessMembersText, displayDoc?.id, parseAccessMembers])

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <IconButton
            label="预览文档内容"
            variant="ghost"
            className="h-8 w-8 text-muted-foreground hover:text-primary hover:bg-muted"
            onClick={(e) => {
              e.stopPropagation()
            }}
          >
            <Eye className="h-4 w-4" />
          </IconButton>
        )}
      </DialogTrigger>

      <DialogContent className="!max-w-5xl h-[80vh] !p-0 !gap-0 overflow-hidden">
        {/* Header */}
        <header className="flex items-start justify-between gap-6 border-b border-border bg-muted/20 px-6 py-4">
          <div className="flex items-start gap-4 min-w-0">
            <div className="grid h-12 w-12 place-items-center rounded-2xl border border-border bg-primary/10 text-primary">
              <Database className="h-6 w-6" />
            </div>
            <div className="min-w-0">
              <DialogTitle className="truncate">{displayDoc.filename}</DialogTitle>
              <DialogDescription className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                <span className="inline-flex items-center gap-1">
                  <FileType className="h-3.5 w-3.5" />
                  {displayDoc.file_type}
                </span>
                <span className="text-muted-foreground/40">|</span>
                <span>{formatFileSize(displayDoc.file_size)}</span>
                <span className="text-muted-foreground/40">|</span>
                <span className="inline-flex items-center gap-1">
                  <Calendar className="h-3.5 w-3.5" />
                  {formatDate(displayDoc.created_at)}
                </span>
                <span className="text-muted-foreground/40">|</span>
                <span className="inline-flex items-center gap-1">
                  <Hash className="h-3.5 w-3.5" />
                  {chunks.length} 切片
                </span>
              </DialogDescription>
            </div>
          </div>

          <div className="flex flex-col items-end gap-2">
            <StatusBadge status={status} />
            <div className="flex flex-wrap justify-end gap-2">
              {parserLabel ? (
                <span className="rounded-full border border-border/60 bg-muted/60 px-2.5 py-1 text-xs font-medium text-muted-foreground">
                  解析：{parserLabel}
                </span>
              ) : null}
              {chunkStrategyLabel ? (
                <span className="rounded-full border border-border/60 bg-muted/60 px-2.5 py-1 text-xs font-medium text-muted-foreground">
                  切块：{chunkStrategyLabel}
                </span>
              ) : null}
              <span className="inline-flex items-center gap-1 rounded-full border border-border/60 bg-muted/60 px-2.5 py-1 text-xs font-medium text-muted-foreground">
                <Shield className="h-3.5 w-3.5" />
                {accessModeLabel}
              </span>
            </div>
          </div>
        </header>

        {/* Body */}
        <main className="min-h-0 p-6 flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Panel className="rounded-2xl">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3 min-w-0">
                  <div className="grid h-10 w-10 place-items-center rounded-2xl border border-border bg-primary/10 text-primary">
                    <FileText className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-foreground">Parse</div>
                    <div className="text-xs text-muted-foreground truncate">{parserLabel || parserBackend || '-'}</div>
                  </div>
                </div>
              </div>
              <div className="mt-3 space-y-1.5">
                <TraceRow label="parser_backend" value={String(pipeline?.parser_backend || parserBackend || '-')} mono />
                <TraceRow
                  label="requested"
                  value={String(pipeline?.parser_backend_requested || docMeta?.parser_backend_requested || '-')}
                  mono
                />
                <TraceRow label="char_count" value={String(analyticsRaw?.char_count ?? '-')} mono />
                <TraceRow label="page_count" value={String(analyticsRaw?.page_count ?? '-')} mono />
                <TraceRow label="table_count" value={String(analyticsRaw?.table_count ?? '-')} mono />
                <TraceRow label="image_count" value={String(analyticsRaw?.image_count ?? '-')} mono />
              </div>
            </Panel>

            <Panel className="rounded-2xl">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3 min-w-0">
                  <div className="grid h-10 w-10 place-items-center rounded-2xl border border-border bg-success/10 text-success">
                    <Shield className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-foreground">Governance</div>
                    <div className="text-xs text-muted-foreground truncate">
                      {displayDoc.governance?.enabled ? 'enabled' : 'disabled'}
                    </div>
                  </div>
                </div>
                {governanceRulePacks.length ? (
                  <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-1 text-[11px] text-muted-foreground">
                    {governanceRulePacks.length} packs
                  </span>
                ) : null}
              </div>
              <div className="mt-3 space-y-1.5">
                <TraceRow label="rules_applied" value={String(displayDoc.governance?.rules_applied ?? '-')} mono />
                <TraceRow label="changed_docs" value={String(displayDoc.governance?.changed_documents ?? '-')} mono />
                <TraceRow label="dropped_docs" value={String(displayDoc.governance?.dropped_documents ?? '-')} mono />
                <TraceRow
                  label="rule_packs"
                  value={governanceRulePacks.length ? governanceRulePacks.slice(0, 4).join(', ') : '-'}
                />
              </div>
            </Panel>

            <Panel className="rounded-2xl">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3 min-w-0">
                  <div className="grid h-10 w-10 place-items-center rounded-2xl border border-border bg-info/10 text-info">
                    <Hash className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-foreground">Chunking</div>
                    <div className="text-xs text-muted-foreground truncate">
                      {chunkStrategyLabel || chunkStrategy || '-'}
                    </div>
                  </div>
                </div>
                {viewingPipelineHash ? (
                  <IconButton
                    label="Copy pipeline_hash"
                    variant="ghost"
                    className="h-9 w-9 text-muted-foreground hover:text-foreground"
                    onClick={() => void copyToClipboard(String(viewingPipelineHash || ''))}
                  >
                    <Copy className="h-4 w-4" />
                  </IconButton>
                ) : null}
              </div>
              <div className="mt-3 space-y-1.5">
                <TraceRow label="viewing_pipeline_hash" value={String(viewingPipelineHash || '-')} mono />
                <TraceRow label="active_pipeline_hash" value={String(activePipelineHash || '-')} mono />
                <TraceRow label="last_pipeline_hash" value={String(lastPipelineHash || '-')} mono />
                <TraceRow label="chunk_size" value={String(pipelineEffective?.chunk_size ?? '-')} mono />
                <TraceRow label="chunk_overlap" value={String(pipelineEffective?.chunk_overlap ?? '-')} mono />
                <TraceRow label="vector_enabled" value={pipelineEffective?.chunk_vector_enabled ? 'true' : 'false'} mono />
                <TraceRow label="bm25_enabled" value={pipelineEffective?.bm25_index_enabled ? 'true' : 'false'} mono />
              </div>
            </Panel>
          </div>

          <Panel className="rounded-2xl">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex items-start gap-3 min-w-0">
                <div className="grid h-10 w-10 place-items-center rounded-2xl border border-border bg-muted/40 text-muted-foreground">
                  <Tags className="h-5 w-5" aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-foreground">Tags</div>
                  <div className="text-xs text-muted-foreground truncate">用于分组与检索过滤（document_user.tags）</div>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 justify-end">
                {tagsEditing ? (
                  <>
                    <Button variant="outline" size="sm" onClick={cancelEditTags} disabled={isSavingTags}>
                      取消
                    </Button>
                    <Button size="sm" onClick={() => void saveTags()} disabled={!canSaveTags}>
                      {isSavingTags ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
                      ) : null}
                      保存
                    </Button>
                  </>
                ) : (
                  <Button variant="outline" size="sm" className="gap-2" onClick={beginEditTags}>
                    <Pencil className="h-4 w-4" aria-hidden="true" />
                    编辑
                  </Button>
                )}
              </div>
            </div>

            <div className="mt-4 space-y-3">
              {tagsEditing ? (
                <TagInput value={tagsDraft} onValueChange={setTagsDraft} disabled={isSavingTags} />
              ) : currentTags.length ? (
                <DocumentTags tags={currentTags} max={10} />
              ) : (
                <div className="text-xs text-muted-foreground">暂无标签（可用于知识库分组、检索过滤与运维标记）</div>
              )}

              {tagsError ? (
                <Alert variant="destructive">
                  <AlertTitle>保存失败</AlertTitle>
                  <AlertDescription>{tagsError}</AlertDescription>
                </Alert>
              ) : null}
            </div>
          </Panel>

          <Panel padding="none" className="flex-1 min-h-0 overflow-hidden rounded-2xl">
            <div className="flex items-center gap-3 border-b border-border/60 bg-background/40 px-4 py-3">
              <div
                className="inline-flex h-10 items-center rounded-md bg-muted p-1 text-muted-foreground"
                role="tablist"
                aria-label="文档详情视图切换"
              >
                <button
                  type="button"
                  className={cn(
                    "inline-flex h-8 items-center justify-center whitespace-nowrap rounded-sm px-3 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none",
                    activeView === "chunks" ? "bg-background text-foreground shadow-sm" : "hover:text-foreground"
                  )}
                  onClick={() => setActiveView("chunks")}
                >
                  切片
                </button>
                <button
                  type="button"
                  className={cn(
                    "inline-flex h-8 items-center justify-center whitespace-nowrap rounded-sm px-3 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none",
                    activeView === "timeline" ? "bg-background text-foreground shadow-sm" : "hover:text-foreground"
                  )}
                  onClick={() => setActiveView("timeline")}
                >
                  时间线
                </button>
              </div>

              {activeView === "chunks" ? (
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={chunkQuery}
                    onChange={(e) => setChunkQuery(e.target.value)}
                    placeholder="搜索切片内容..."
                    className="h-10 pl-9"
                  />
                </div>
              ) : (
                <div className="flex-1 text-sm text-muted-foreground">文档处理时间线（可回溯）</div>
              )}

              {activeView === "chunks" && versions?.items?.length ? (
                <Select value={viewPipelineHash} onValueChange={setViewPipelineHash}>
                  <SelectTrigger className="hidden h-10 w-[220px] sm:flex">
                    <SelectValue placeholder="选择版本" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ACTIVE_PIPELINE_VALUE}>当前激活版本</SelectItem>
                    {versions.items.map((v) => (
                      <SelectItem key={v.pipeline_hash} value={v.pipeline_hash}>
                        {v.active ? '激活' : '历史'} {v.pipeline_hash.slice(0, 10)}… · {v.chunk_count} chunks
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : null}

              <span className="hidden sm:inline-flex rounded-full border border-border/60 bg-muted/60 px-2 py-1 text-xs text-muted-foreground">
                {activeView === "chunks"
                  ? `${chunks.length}/${chunksTotal}`
                  : `${timelineItems.length}/${timelineTotal}`}
              </span>

              {activeView === "chunks" ? (
                chunkQuery ? (
                  <IconButton
                    label="清除搜索"
                    variant="ghost"
                    className="h-10 w-10 text-muted-foreground hover:text-foreground"
                    onClick={() => setChunkQuery("")}
                  >
                    <X className="h-4 w-4" />
                  </IconButton>
                ) : null
              ) : (
                <IconButton
                  label="刷新时间线"
                  variant="ghost"
                  className="h-10 w-10 text-muted-foreground hover:text-foreground"
                  onClick={() => void loadTimeline()}
                  disabled={isLoadingTimeline}
                >
                  {isLoadingTimeline ? (
                    <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                  ) : (
                    <RefreshCw className="h-4 w-4" />
                  )}
                </IconButton>
              )}
            </div>

            <div ref={scrollParentRef} className="h-full overflow-y-auto overscroll-contain no-scrollbar p-4">
              {activeView === "chunks" ? (
                (isLoadingDoc && !detail) || (isLoadingChunks && chunks.length === 0) ? (
                  <div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
                    <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none" />
                    <p className="text-sm">正在加载切片数据...</p>
                  </div>
                ) : loadError && chunks.length === 0 ? (
                  <div className="mx-auto max-w-2xl py-10">
                    <Alert variant="destructive">
                      <AlertTitle>加载失败</AlertTitle>
                      <AlertDescription>{loadError}</AlertDescription>
                    </Alert>
                    <div className="mt-4 flex items-center justify-end gap-2">
                      <Button
                        variant="outline"
                        onClick={() => {
                          void loadDetail()
                          void loadVersions()
                          void reloadChunks()
                        }}
                      >
                        重试
                      </Button>
                      <Button variant="secondary" onClick={() => setOpen(false)}>
                        关闭
                      </Button>
                    </div>
                  </div>
                ) : chunksTotal === 0 && !isSearching ? (
                  <EmptyState
                    icon={FileText}
                    title="暂无切片数据"
                    description="该文档暂未生成可用切片，或后端未返回切片内容。"
                    className="min-h-[320px]"
                  />
                ) : chunksTotal === 0 && isSearching ? (
                  <EmptyState
                    icon={Search}
                    title="未找到匹配切片"
                    description={<span>尝试更换关键词，或清空筛选条件。</span>}
                    className="min-h-[320px]"
	                  >
	                    <Button variant="outline" onClick={() => setChunkQuery("")}>
	                      清空筛选
	                    </Button>
	                  </EmptyState>
	                ) : (
	                  <div className="pb-6 space-y-3">
	                    {chunkError && chunks.length > 0 ? (
	                      <Alert variant="destructive">
	                        <AlertTitle>加载切片失败</AlertTitle>
	                        <AlertDescription>{chunkError}</AlertDescription>
	                      </Alert>
	                    ) : null}
	
	                    <div
	                      role="list"
	                      aria-label="文档切片列表"
	                      style={{
	                        height: `${chunkRowVirtualizer.getTotalSize()}px`,
	                        width: '100%',
	                        position: 'relative',
	                      }}
	                    >
	                      {chunkRowVirtualizer.getVirtualItems().map((virtualRow) => {
	                        const chunk = chunks[virtualRow.index]
	                        if (!chunk) return null
	
	                        return (
	                          <div
	                            key={virtualRow.key}
	                            data-index={virtualRow.index}
	                            ref={chunkRowVirtualizer.measureElement}
	                            role="listitem"
	                            style={{
	                              position: 'absolute',
	                              top: 0,
	                              left: 0,
	                              width: '100%',
	                              transform: `translateY(${virtualRow.start}px)`,
	                            }}
	                            className="pb-3"
	                          >
	                            <div
	                              className={cn(
	                                "group rounded-xl border border-border/60 bg-card p-4 transition-colors",
	                                "hover:border-primary/25 hover:shadow-soft/30",
	                                chunk.disabled_at ? "opacity-70" : null
	                              )}
	                            >
	                              <div className="flex items-start justify-between gap-3">
	                                <div className="flex flex-wrap items-center gap-2 text-xs">
	                                  <span className="rounded-full border border-border/60 bg-muted px-2 py-0.5 font-mono font-medium text-muted-foreground">
	                                    #{chunk.chunk_index}
	                                  </span>
	                                  {typeof chunk.page_number === "number" ? (
	                                    <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-muted-foreground">
	                                      P.{chunk.page_number}
	                                    </span>
	                                  ) : null}
	                                  <span className="text-muted-foreground">{(chunk.content || "").length} chars</span>
	                                  {chunk.disabled_at ? (
	                                    <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-muted-foreground">
	                                      disabled
	                                    </span>
	                                  ) : null}
	                                </div>
	                                <div className="flex items-center gap-1">
	                                  <IconButton
	                                    label={canMutateChunks ? "编辑切片" : "仅当前激活版本可编辑"}
	                                    variant="ghost"
	                                    className="h-9 w-9 text-muted-foreground hover:text-foreground"
	                                    onClick={() => beginEditChunk(chunk)}
	                                    disabled={!canMutateChunks || chunkOpWorkingId === chunk.id}
	                                  >
	                                    <Pencil className="h-4 w-4" />
	                                  </IconButton>
	                                  <IconButton
	                                    label={chunk.disabled_at ? "启用切片" : "禁用切片"}
	                                    variant="ghost"
	                                    className="h-9 w-9 text-muted-foreground hover:text-foreground"
	                                    onClick={() => void toggleChunkDisabled(chunk)}
	                                    disabled={!canMutateChunks || chunkOpWorkingId === chunk.id}
	                                  >
	                                    {chunk.disabled_at ? <CheckCircle2 className="h-4 w-4" /> : <Ban className="h-4 w-4" />}
	                                  </IconButton>
	                                  <IconButton
	                                    label={chunk.disabled_at ? "禁用切片不能 re-embed" : "重新嵌入切片"}
	                                    variant="ghost"
	                                    className="h-9 w-9 text-muted-foreground hover:text-foreground"
	                                    onClick={() => void reembedChunk(chunk)}
	                                    disabled={!canMutateChunks || Boolean(chunk.disabled_at) || chunkOpWorkingId === chunk.id}
	                                  >
	                                    <RefreshCw className="h-4 w-4" />
	                                  </IconButton>
	                                  <IconButton
	                                    label="复制切片内容"
	                                    variant="ghost"
	                                    className="h-9 w-9 text-muted-foreground hover:text-foreground"
	                                    onClick={() => void copyToClipboard(chunk.content)}
	                                    disabled={chunkOpWorkingId === chunk.id}
	                                  >
	                                    <Copy className="h-4 w-4" />
	                                  </IconButton>
	                                </div>
	                              </div>
	
	                              {editingChunkId === chunk.id ? (
	                                <div className="mt-3 space-y-2">
	                                  <Textarea
	                                    value={editingChunkContent}
	                                    onChange={(e) => setEditingChunkContent(e.target.value)}
	                                    className="min-h-[140px] font-mono text-xs"
	                                    disabled={!canMutateChunks || chunkOpWorkingId === chunk.id}
	                                  />
	                                  <div className="flex items-center justify-end gap-2">
	                                    <Button
	                                      type="button"
	                                      variant="outline"
	                                      size="sm"
	                                      onClick={cancelEditChunk}
	                                      disabled={chunkOpWorkingId === chunk.id}
	                                    >
	                                      取消
	                                    </Button>
	                                    <Button
	                                      type="button"
	                                      size="sm"
	                                      onClick={() => void saveEditChunk()}
	                                      disabled={!canMutateChunks || chunkOpWorkingId === chunk.id}
	                                      className="gap-2"
	                                    >
	                                      {chunkOpWorkingId === chunk.id ? (
	                                        <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
	                                      ) : (
	                                        <Save className="h-4 w-4" />
	                                      )}
	                                      保存
	                                    </Button>
	                                  </div>
	                                </div>
	                              ) : (
	                                <div className="mt-2 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground/90">
	                                  {highlightText(chunk.content || "", chunkQuery)}
	                                </div>
	                              )}
	                            </div>
	                          </div>
	                        )
	                      })}
	                    </div>
	
	                    {canLoadMoreChunks ? (
	                      <div className="flex justify-center pt-2">
	                        <Button
	                          variant="outline"
	                          onClick={() => void loadMoreChunks()}
	                          disabled={isLoadingChunks}
	                          className="gap-2"
	                        >
	                          {isLoadingChunks ? (
	                            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
	                          ) : null}
	                          加载更多
	                        </Button>
	                      </div>
	                    ) : null}
	                  </div>
	                )
	              ) : isLoadingTimeline && timelineItems.length === 0 ? (
	                <div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
	                  <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none" />
                  <p className="text-sm">正在加载时间线...</p>
                </div>
              ) : (timelineError || docError) && timelineItems.length === 0 ? (
                <div className="mx-auto max-w-2xl py-10">
                  <Alert variant="destructive">
                    <AlertTitle>加载失败</AlertTitle>
                    <AlertDescription>{timelineError || docError}</AlertDescription>
                  </Alert>
                  <div className="mt-4 flex items-center justify-end gap-2">
                    <Button variant="outline" onClick={() => void loadTimeline()}>
                      重试
                    </Button>
                    <Button variant="secondary" onClick={() => setOpen(false)}>
                      关闭
                    </Button>
                  </div>
                </div>
              ) : timelineItems.length === 0 ? (
                <EmptyState
                  icon={Calendar}
                  title="暂无时间线事件"
	                  description="该文档暂未产生可回溯的事件记录（或审计未启用）。"
	                  className="min-h-[320px]"
	                />
	              ) : (
	                <div className="pb-6 space-y-3">
	                  {timelineError ? (
	                    <Alert variant="destructive">
	                      <AlertTitle>加载时间线失败</AlertTitle>
	                      <AlertDescription>{timelineError}</AlertDescription>
	                    </Alert>
	                  ) : null}
	
	                  <div
	                    role="list"
	                    aria-label="文档时间线"
	                    style={{
	                      height: `${timelineRowVirtualizer.getTotalSize()}px`,
	                      width: '100%',
	                      position: 'relative',
	                    }}
	                  >
	                    {timelineRowVirtualizer.getVirtualItems().map((virtualRow) => {
	                      const ev = timelineItems[virtualRow.index]
	                      if (!ev) return null
	                      const detailPairs = Object.entries(ev.details || {}).slice(0, 12)
	                      const hasDetails = detailPairs.length > 0
	
	                      return (
	                        <div
	                          key={virtualRow.key}
	                          data-index={virtualRow.index}
	                          ref={timelineRowVirtualizer.measureElement}
	                          role="listitem"
	                          style={{
	                            position: 'absolute',
	                            top: 0,
	                            left: 0,
	                            width: '100%',
	                            transform: `translateY(${virtualRow.start}px)`,
	                          }}
	                          className="pb-3"
	                        >
	                          <div
	                            className={cn(
	                              "group rounded-xl border border-border/60 bg-card p-4 transition-colors",
	                              "hover:border-primary/25 hover:shadow-soft/30"
	                            )}
	                          >
	                            <div className="flex items-start justify-between gap-3">
	                              <div className="min-w-0">
	                                <div className="flex flex-wrap items-center gap-2">
	                                  <span className="rounded-full border border-border/60 bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground">
	                                    {formatDate(ev.created_at)}
	                                  </span>
	                                  <span className="truncate font-mono text-xs text-foreground/90">{ev.action}</span>
	                                  {ev.source === "synthetic" ? (
	                                    <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-xs text-muted-foreground">
	                                      synthetic
	                                    </span>
	                                  ) : null}
	                                </div>
	
	                                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
	                                  {ev.stage ? <span>stage: {ev.stage}</span> : null}
	                                  {ev.status ? <span>status: {ev.status}</span> : null}
	                                  {typeof ev.progress === "number" ? <span>progress: {ev.progress}%</span> : null}
	                                  {ev.request_id ? (
	                                    <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 font-mono">
	                                      req: {ev.request_id}
	                                    </span>
	                                  ) : null}
	                                  {ev.actor_id ? (
	                                    <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 font-mono">
	                                      by: {ev.actor_id}
	                                    </span>
	                                  ) : null}
	                                </div>
	                              </div>
	
	                              <IconButton
	                                label="复制事件信息"
	                                variant="ghost"
	                                className="h-9 w-9 text-muted-foreground hover:text-foreground"
	                                onClick={() =>
	                                  void copyToClipboard(
	                                    JSON.stringify(
	                                      {
	                                        id: ev.id,
	                                        action: ev.action,
	                                        created_at: ev.created_at,
	                                        stage: ev.stage,
	                                        status: ev.status,
	                                        progress: ev.progress,
	                                        request_id: ev.request_id,
	                                        actor_id: ev.actor_id,
	                                        details: ev.details,
	                                      },
	                                      null,
	                                      2
	                                    )
	                                  )
	                                }
	                              >
	                                <Copy className="h-4 w-4" />
	                              </IconButton>
	                            </div>
	
	                            {hasDetails ? (
	                              <div className="mt-3 flex flex-wrap gap-2">
	                                {detailPairs.map(([k, v]) => (
	                                  <span
	                                    key={`${ev.id}:${k}`}
	                                    className="rounded-md border border-border/60 bg-muted/40 px-2 py-1 font-mono text-[11px] text-muted-foreground"
	                                    title={`${k}: ${String(v)}`}
	                                  >
	                                    {k}: {String(v)}
	                                  </span>
	                                ))}
	                              </div>
	                            ) : null}
	                          </div>
	                        </div>
	                      )
	                    })}
	                  </div>
	                </div>
	              )}
            </div>
          </Panel>
        </main>

        {/* Footer */}
        <footer className="border-t border-border bg-muted/20 px-6 py-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-col gap-2 sm:flex-row">
              <Dialog
                open={versionsDialogOpen}
                onOpenChange={(next) => {
                  setVersionsDialogOpen(next)
                  if (next) {
                    void loadVersions()
                  }
                }}
              >
                <DialogTrigger asChild>
                  <Button variant="outline" className="w-full gap-2 sm:w-auto">
                    <Hash className="h-4 w-4" />
                    版本
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-2xl">
                  <DialogTitle>文档版本（pipeline）</DialogTitle>
                  <DialogDescription className="text-xs">
                    用于运维/回滚：不同 pipeline 配置会生成不同的 <span className="font-mono">pipeline_hash</span> 版本；激活版本会影响检索与引用。
                  </DialogDescription>

                  <div className="mt-4 space-y-3">
                    {isLoadingVersions ? (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                        正在加载版本信息...
                      </div>
                    ) : versionsError ? (
                      <Alert variant="destructive">
                        <AlertTitle>加载版本失败</AlertTitle>
                        <AlertDescription className="flex items-center justify-between gap-3">
                          <span className="min-w-0 flex-1">{versionsError}</span>
                          <Button variant="outline" size="sm" onClick={() => void loadVersions()}>
                            重试
                          </Button>
                        </AlertDescription>
                      </Alert>
                    ) : null}

                    <div className="rounded-xl border border-border/60 bg-muted/20 p-3">
                      <div className="text-xs text-muted-foreground">当前激活 pipeline_hash</div>
                      <div className="mt-2 flex items-center justify-between gap-2">
                        <div className="min-w-0 font-mono text-xs text-foreground">
                          {versions?.active_pipeline_hash || '-'}
                        </div>
                        <IconButton
                          label="复制 pipeline_hash"
                          variant="ghost"
                          className="h-9 w-9 text-muted-foreground hover:text-foreground"
                          disabled={!versions?.active_pipeline_hash}
                          onClick={() => void copyToClipboard(String(versions?.active_pipeline_hash || ''))}
                        >
                          <Copy className="h-4 w-4" />
                        </IconButton>
                      </div>
                    </div>

                    {!isLoadingVersions && !versionsError ? (
                      versions?.items?.length ? (
                        <div className="space-y-2">
                          {versions.items.map((v) => (
                            <div
                              key={v.pipeline_hash}
                              className={cn(
                                "flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-card p-3",
                                v.active ? "border-primary/30 bg-primary/5" : "bg-card"
                              )}
                            >
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="font-mono text-xs text-foreground">{v.pipeline_hash}</span>
                                  {v.active ? (
                                    <span className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                                      ACTIVE
                                    </span>
                                  ) : null}
                                </div>
                                <div className="mt-1 text-xs text-muted-foreground">
                                  {v.chunk_count} chunks
                                  {v.last_chunk_at ? ` · 更新 ${formatDate(v.last_chunk_at)}` : ''}
                                </div>
                              </div>

                              <div className="flex flex-shrink-0 items-center gap-2">
                                <IconButton
                                  label="复制版本 hash"
                                  variant="ghost"
                                  className="h-9 w-9 text-muted-foreground hover:text-foreground"
                                  onClick={() => void copyToClipboard(v.pipeline_hash)}
                                >
                                  <Copy className="h-4 w-4" />
                                </IconButton>

                                {v.active ? (
                                  <Button size="sm" variant="secondary" disabled>
                                    已激活
                                  </Button>
                                ) : (
                                  <>
                                    <ConfirmDialog
                                      title="切换激活版本？"
                                      description={
                                        <>
                                          将把激活版本切换为 <span className="font-mono">{v.pipeline_hash.slice(0, 12)}…</span>。这不会重新解析/重新向量化，只会影响检索与引用。
                                        </>
                                      }
                                      confirmLabel="切换"
                                      cancelLabel="返回"
                                      confirmVariant="default"
                                      confirmDisabled={isVersionWorking}
                                      onConfirm={() => void handleActivateVersion(v.pipeline_hash)}
                                    >
                                      <Button size="sm" variant="outline" disabled={isVersionWorking}>
                                        激活
                                      </Button>
                                    </ConfirmDialog>
                                    <ConfirmDialog
                                      title="删除该版本？"
                                      description={
                                        <>
                                          将删除版本 <span className="font-mono">{v.pipeline_hash.slice(0, 12)}…</span>。注意：当前激活版本无法删除。
                                        </>
                                      }
                                      confirmLabel="删除"
                                      cancelLabel="返回"
                                      confirmVariant="destructive"
                                      confirmDisabled={isVersionWorking}
                                      onConfirm={() => void handleDeleteVersion(v.pipeline_hash)}
                                    >
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        disabled={isVersionWorking}
                                        className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                                      >
                                        删除
                                      </Button>
                                    </ConfirmDialog>
                                  </>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <EmptyState
                          icon={Hash}
                          title="暂无版本信息"
                          description="当前文档还没有可用的 pipeline 版本记录（或尚未生成切片）。"
                          className="min-h-[240px]"
                        />
                      )
                    ) : null}

                    <div className="text-xs text-muted-foreground">
                      提示：激活/删除版本需要对文档所属数据集有写权限；删除操作不可恢复。
                    </div>
                  </div>
                </DialogContent>
              </Dialog>

              <Dialog
                open={accessDialogOpen}
                onOpenChange={(next) => {
                  if (next) {
                    setAccessMode(effectiveAccessMode)
                    setAccessMembersText((accessInfo?.partial_member_list || []).join('\n'))
                  }
                  setAccessDialogOpen(next)
                }}
              >
                <DialogTrigger asChild>
                  <Button variant="outline" className="w-full gap-2 sm:w-auto">
                    <Shield className="h-4 w-4" />
                    访问控制
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-xl">
                  <DialogTitle>文档访问控制</DialogTitle>
                  <DialogDescription className="text-xs">
                    用于“安全裁剪（security trimming）”：在数据集权限基础上进一步限制该文档的可见范围。
                  </DialogDescription>

                  <div className="mt-4 space-y-4">
                    <div className="space-y-2">
                      <div className="text-sm font-medium">模式</div>
                      <Select value={accessMode} onValueChange={(v) => setAccessMode(v as DocumentAccessMode)}>
                        <SelectTrigger>
                          <SelectValue placeholder="选择访问模式" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="inherit">继承数据集</SelectItem>
                          <SelectItem value="only_me">仅我可见</SelectItem>
                          <SelectItem value="partial_members">指定成员</SelectItem>
                          <SelectItem value="all_team_members">团队成员</SelectItem>
                        </SelectContent>
                      </Select>
                      <div className="text-xs text-muted-foreground">
                        Owner：<span className="font-mono">{displayDoc.owner_id || '-'}</span>
                      </div>
                    </div>

                    {accessMode === 'partial_members' ? (
                      <div className="space-y-2">
                        <div className="text-sm font-medium">允许成员（每行一个 user_id）</div>
                        <Textarea
                          value={accessMembersText}
                          onChange={(e) => setAccessMembersText(e.target.value)}
                          placeholder="例如：\nalice\nbob\ncharlie"
                        />
                        <div className="text-xs text-muted-foreground">最多 200 个；仅支持当前租户已存在的成员。</div>
                      </div>
                    ) : null}
                  </div>

                  <div className="mt-6 flex items-center justify-end gap-2">
                    <Button variant="outline" onClick={() => setAccessDialogOpen(false)} disabled={isSavingAccess}>
                      取消
                    </Button>
                    <Button onClick={() => void handleSaveAccess()} disabled={isSavingAccess}>
                      {isSavingAccess ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
                      ) : null}
                      保存
                    </Button>
                  </div>
                </DialogContent>
              </Dialog>

              <Button variant="outline" onClick={handleExtractKG} disabled={!canRunKg} className="w-full gap-2 sm:w-auto">
                {isKgWorking && canRunKg ? (
                  <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                ) : null}
                抽取 KG
              </Button>
              <ConfirmDialog
                title="清理 KG 事件？"
                description="将删除该文档的 KG 事件，并尝试清理孤儿实体。此操作不可恢复。"
                confirmLabel="清理"
                cancelLabel="返回"
                confirmVariant="destructive"
                confirmDisabled={isKgWorking}
                onConfirm={() => void handleDeleteKG()}
              >
                <Button
                  variant="outline"
                  disabled={isKgWorking}
                  className="w-full gap-2 text-destructive hover:bg-destructive/10 hover:text-destructive sm:w-auto"
                >
                  清理 KG
                </Button>
              </ConfirmDialog>
            </div>

            <Button variant="secondary" onClick={() => setOpen(false)} className="w-full sm:w-auto">
              关闭
            </Button>
          </div>
        </footer>
      </DialogContent>
    </Dialog>
  )
}
