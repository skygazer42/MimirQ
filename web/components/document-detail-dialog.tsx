/**
 * 文档详情对话框 - 展示最终切片结果
 */
'use client'

import { startTransition, useActionState, useCallback, useEffect, useId, useMemo, useOptimistic, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react'
import { useFormStatus } from 'react-dom'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Ban, Calendar, CheckCircle2, Copy, Database, Eye, FileText, FileType, Hash, Loader2, Pencil, RefreshCw, Save, Search, Shield, Tags, X } from 'lucide-react'
import { toast } from 'sonner'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { DocumentAccessDialog } from '@/components/document-detail-dialog/document-access-dialog'
import { DocumentVersionsDialog } from '@/components/document-detail-dialog/document-versions-dialog'
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
import { documentApi, kgApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { buildTagsPatch, getUserTagsFromDocument, normalizeTags } from '@/lib/document-user-tags'
import { messages } from '@/lib/messages'
import { getParserLabel } from '@/lib/parser-options'
import { cn, formatDate, formatFileSize, detachPromise } from '@/lib/utils'
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
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
type DocumentPublicationStatus = 'draft' | 'published' | 'deprecated'
type LifecycleDraftValues = {
  publicationStatus: DocumentPublicationStatus
  owner: string
  reviewDueAt: string
  authorityLevel: string
  supersedesDocumentId: string
}

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

function TraceRow({ label, value, mono }: Readonly<{ label: string; value: string; mono?: boolean }>) {
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

function toDatetimeLocalValue(value: string | null | undefined): string {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function normalizeAccessMode(value: FormDataEntryValue | string | null | undefined): DocumentAccessMode {
  const normalized = String(value || '').trim()
  switch (normalized) {
    case 'inherit':
    case 'only_me':
    case 'partial_members':
    case 'all_team_members':
      return normalized
    default:
      return 'inherit'
  }
}

function parseStringArrayField(value: FormDataEntryValue | string | null | undefined): string[] {
  let parsed: unknown = []
  try {
    parsed = JSON.parse(String(value || '[]'))
  } catch {
    parsed = []
  }

  if (!Array.isArray(parsed)) return []

  const out: string[] = []
  const seen = new Set<string>()
  for (const item of parsed) {
    const next = String(item || '').trim()
    if (!next || seen.has(next)) continue
    seen.add(next)
    out.push(next)
    if (out.length >= 200) break
  }

  return out
}

function normalizePublicationStatus(value: FormDataEntryValue | string | null | undefined): DocumentPublicationStatus {
  const normalized = String(value || '').trim()
  return normalized === 'draft' || normalized === 'deprecated' ? normalized : 'published'
}

function getLifecycleValidationError(values: Pick<LifecycleDraftValues, 'authorityLevel' | 'reviewDueAt' | 'supersedesDocumentId'>) {
  const sup = values.supersedesDocumentId.trim()
  if (sup && !UUID_RE.test(sup)) return 'supersedes_document_id 不是合法 UUID'

  const auth = values.authorityLevel.trim()
  if (auth) {
    const n = Number.parseInt(auth, 10)
    if (!Number.isFinite(n)) return 'authority_level 必须是整数'
    if (n < 0 || n > 100) return 'authority_level 需在 0-100 之间'
  }

  const due = values.reviewDueAt.trim()
  if (due) {
    const d = new Date(due)
    if (Number.isNaN(d.getTime())) return 'review_due_at 不是合法时间'
  }

  return null
}

function hasLifecycleChanges(doc: Document, values: LifecycleDraftValues) {
  const currentPublicationStatus = String(doc.publication_status || 'published').trim()
  const currentOwner = String(doc.lifecycle_owner || '').trim()
  const currentReviewDueAt = toDatetimeLocalValue(doc.review_due_at)
  const currentAuthorityLevel = doc.authority_level == null ? '' : String(doc.authority_level)
  const currentSupersedesDocumentId = String(doc.supersedes_document_id || '').trim()

  return (
    currentPublicationStatus !== values.publicationStatus ||
    currentOwner !== values.owner ||
    currentReviewDueAt !== values.reviewDueAt ||
    currentAuthorityLevel !== values.authorityLevel ||
    currentSupersedesDocumentId !== values.supersedesDocumentId
  )
}

function DocumentTagsSaveButton({ disabled }: Readonly<{ disabled: boolean }>) {
  const { pending } = useFormStatus()

  return (
    <Button size="sm" type="submit" disabled={disabled || pending}>
      {pending ? (
        <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
      ) : null}
      保存
    </Button>
  )
}

function DocumentLifecycleSaveButton({ disabled }: Readonly<{ disabled: boolean }>) {
  const { pending } = useFormStatus()

  return (
    <Button size="sm" type="submit" disabled={disabled || pending}>
      {pending ? (
        <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
      ) : null}
      保存
    </Button>
  )
}

export function DocumentDetailDialog({ document: initialDocument, trigger }: Readonly<DocumentDetailDialogProps>) {
  const viewTabsId = useId()
  const chunksTabId = `${viewTabsId}-chunks-tab`
  const timelineTabId = `${viewTabsId}-timeline-tab`
  const chunksPanelId = `${viewTabsId}-chunks-panel`
  const timelinePanelId = `${viewTabsId}-timeline-panel`
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

  const persistedTags = useMemo(() => getUserTagsFromDocument(detail || initialDocument), [detail, initialDocument])
  const [optimisticTags, applyOptimisticTags] = useOptimistic(
    persistedTags,
    (_currentTags, nextTags: string[]) => normalizeTags(nextTags)
  )
  const [tagsEditing, setTagsEditing] = useState(false)
  const [tagsDraft, setTagsDraft] = useState<string[]>([])
  const [tagsError, setTagsError] = useState<string | null>(null)

  const [lifecycleWritable, setLifecycleWritable] = useState<boolean | null>(null)
  const [lifecyclePermError, setLifecyclePermError] = useState<string | null>(null)
  const [lifecycleEditing, setLifecycleEditing] = useState(false)
  const [lifecyclePublicationStatusDraft, setLifecyclePublicationStatusDraft] = useState<
    'draft' | 'published' | 'deprecated'
  >('published')
  const [lifecycleOwnerDraft, setLifecycleOwnerDraft] = useState('')
  const [lifecycleReviewDueDraft, setLifecycleReviewDueDraft] = useState('')
  const [lifecycleAuthorityDraft, setLifecycleAuthorityDraft] = useState('')
  const [lifecycleSupersedesDraft, setLifecycleSupersedesDraft] = useState('')
  const [lifecycleError, setLifecycleError] = useState<string | null>(null)

  const canMutateChunks = viewPipelineHash === ACTIVE_PIPELINE_VALUE

  const focusViewTab = useCallback((nextView: 'chunks' | 'timeline') => {
    setActiveView(nextView)
    globalThis.window.requestAnimationFrame(() => {
      globalThis.document.getElementById(nextView === 'chunks' ? chunksTabId : timelineTabId)?.focus()
    })
  }, [chunksTabId, timelineTabId])

  const handleViewTabKeyDown = useCallback((event: ReactKeyboardEvent<HTMLButtonElement>) => {
    switch (event.key) {
      case 'ArrowLeft':
      case 'ArrowUp':
        event.preventDefault()
        focusViewTab('chunks')
        break
      case 'ArrowRight':
      case 'ArrowDown':
        event.preventDefault()
        focusViewTab('timeline')
        break
      case 'Home':
        event.preventDefault()
        focusViewTab('chunks')
        break
      case 'End':
        event.preventDefault()
        focusViewTab('timeline')
        break
      default:
        break
    }
  }, [focusViewTab])

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
    setTagsDraft(persistedTags)
    setTagsEditing(true)
  }, [persistedTags])

  const cancelEditTags = useCallback(() => {
    setTagsError(null)
    setTagsDraft([])
    setTagsEditing(false)
  }, [])

  const hasPendingTagChanges = useMemo(() => {
    if (!tagsEditing) return false
    const next = normalizeTags(tagsDraft)
    if (next.length !== persistedTags.length) return true
    for (let i = 0; i < next.length; i += 1) {
      if (next[i] !== persistedTags[i]) return true
    }
    return false
  }, [persistedTags, tagsDraft, tagsEditing])

  const [, saveTagsAction, isSavingTags] = useActionState(async (_state: null, formData: FormData) => {
    if (!tagsEditing) return null

    let parsedTags: unknown = []
    try {
      parsedTags = JSON.parse(String(formData.get('tags_json') || '[]'))
    } catch {
      parsedTags = []
    }

    const nextTags = normalizeTags(parsedTags)
    if (nextTags.length === persistedTags.length && nextTags.every((tag, index) => tag === persistedTags[index])) {
      return null
    }

    setTagsError(null)
    startTransition(() => {
      applyOptimisticTags(nextTags)
    })
    setTagsEditing(false)
    setTagsDraft([])

    try {
      const updated = await documentApi.patchUserMetadata(initialDocument.id, buildTagsPatch(nextTags))
      setDetail(updated)
      toast.success('已更新标签')
    } catch (err: any) {
      console.error('Update document tags failed:', err)
      const msg = formatApiError(err, '保存标签失败')
      setTagsError(msg)
      setTagsDraft(nextTags)
      setTagsEditing(true)
      toast.error(msg)
    }

    return null
  }, null)

  const canSaveTags = hasPendingTagChanges && !isSavingTags

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
        const res = await documentApi.reembedChunks(initialDocument.id, {
          chunk_ids: [chunk.id],
          include_disabled: Boolean(chunk.disabled_at),
        })
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
  const [accessGroupIds, setAccessGroupIds] = useState<string[]>([])

  const loadDetail = useCallback(async () => {
    setIsLoadingDoc(true)
    setDocError(null)
    setLifecyclePermError(null)
    setLifecycleWritable(null)
    try {
      const [data, acl, lifecyclePerm] = await Promise.all([
        documentApi.get(initialDocument.id),
        documentApi.getAccess(initialDocument.id).catch((err) => {
          console.warn('Load document access error:', err)
          return null
        }),
        documentApi
          .getLifecycleMetadata(initialDocument.id)
          .then(() => ({ writable: true, error: null }))
          .catch((err) => {
            const status = err?.response?.status
            if (status === 403) return { writable: false, error: null }
            return { writable: null, error: formatApiError(err, '无法确认 lifecycle 编辑权限') }
          }),
      ])
      setDetail(data)
      setAccessInfo(acl)
      setLifecycleWritable(lifecyclePerm.writable)
      if (lifecyclePerm.error) setLifecyclePermError(lifecyclePerm.error)
    } catch (err: any) {
      console.error('Load document detail error:', err)
      setDocError(formatApiError(err, '获取文档详情失败'))
    } finally {
      setIsLoadingDoc(false)
    }
  }, [initialDocument.id])

  const beginEditLifecycle = useCallback(() => {
    const doc = detail || initialDocument
    setLifecycleError(null)
    const ps = String(doc.publication_status || 'published').trim()
    setLifecyclePublicationStatusDraft(ps === 'draft' || ps === 'deprecated' ? ps : 'published')
    setLifecycleOwnerDraft(String(doc.lifecycle_owner || ''))
    setLifecycleReviewDueDraft(toDatetimeLocalValue(doc.review_due_at))
    setLifecycleAuthorityDraft(doc.authority_level == null ? '' : String(doc.authority_level))
    setLifecycleSupersedesDraft(String(doc.supersedes_document_id || ''))
    setLifecycleEditing(true)
  }, [detail, initialDocument])

  const cancelEditLifecycle = useCallback(() => {
    setLifecycleError(null)
    setLifecyclePublicationStatusDraft('published')
    setLifecycleOwnerDraft('')
    setLifecycleReviewDueDraft('')
    setLifecycleAuthorityDraft('')
    setLifecycleSupersedesDraft('')
    setLifecycleEditing(false)
  }, [])

  const lifecycleDraftValues = useMemo<LifecycleDraftValues>(() => ({
    publicationStatus: lifecyclePublicationStatusDraft,
    owner: lifecycleOwnerDraft.trim(),
    reviewDueAt: lifecycleReviewDueDraft.trim(),
    authorityLevel: lifecycleAuthorityDraft.trim(),
    supersedesDocumentId: lifecycleSupersedesDraft.trim(),
  }), [
    lifecycleAuthorityDraft,
    lifecycleOwnerDraft,
    lifecyclePublicationStatusDraft,
    lifecycleReviewDueDraft,
    lifecycleSupersedesDraft,
  ])

  const lifecycleValidationError = useMemo(
    () => getLifecycleValidationError(lifecycleDraftValues),
    [lifecycleDraftValues]
  )

  const lifecycleHasChanges = useMemo(
    () => hasLifecycleChanges(detail || initialDocument, lifecycleDraftValues),
    [detail, initialDocument, lifecycleDraftValues]
  )

  const [, saveLifecycleAction, isSavingLifecycle] = useActionState(async (_state: null, formData: FormData) => {
    if (!lifecycleEditing) return null

    const nextValues: LifecycleDraftValues = {
      publicationStatus: normalizePublicationStatus(formData.get('publication_status')),
      owner: String(formData.get('lifecycle_owner') || '').trim(),
      reviewDueAt: String(formData.get('review_due_at') || '').trim(),
      authorityLevel: String(formData.get('authority_level') || '').trim(),
      supersedesDocumentId: String(formData.get('supersedes_document_id') || '').trim(),
    }

    const validationError = getLifecycleValidationError(nextValues)
    if (validationError) {
      setLifecycleError(validationError)
      return null
    }

    const currentDoc = detail || initialDocument
    if (!hasLifecycleChanges(currentDoc, nextValues)) {
      return null
    }

    setLifecycleError(null)

    try {
      await documentApi.patchLifecycleMetadata(initialDocument.id, {
        publication_status: nextValues.publicationStatus,
        lifecycle_owner: nextValues.owner || null,
        supersedes_document_id: nextValues.supersedesDocumentId || null,
        authority_level: nextValues.authorityLevel ? Number.parseInt(nextValues.authorityLevel, 10) : null,
        review_due_at: nextValues.reviewDueAt ? new Date(nextValues.reviewDueAt).toISOString() : null,
      })
      toast.success('已更新 lifecycle 信息')
      cancelEditLifecycle()
      await loadDetail()
    } catch (err: any) {
      console.error('Update document lifecycle metadata failed:', err)
      const msg = formatApiError(err, '保存 lifecycle 信息失败')
      setLifecycleError(msg)
      toast.error(msg)
    }

    return null
  }, null)

  const canSaveLifecycle = lifecycleEditing && !isSavingLifecycle && !lifecycleValidationError && lifecycleHasChanges

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
        q: q || undefined,
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
    detachPromise(loadDetail())
    detachPromise(loadVersions())
  }, [open, loadDetail, loadVersions])

  useEffect(() => {
    if (!open) return
    if (activeView !== 'chunks') return
    const handle = globalThis.window.setTimeout(() => {
      detachPromise(reloadChunks())
    }, chunkQuery.trim() ? 250 : 0)
    return () => globalThis.window.clearTimeout(handle)
  }, [open, activeView, chunkQuery, viewPipelineHash, reloadChunks])

  useEffect(() => {
    if (!open) return
    if (activeView !== 'timeline') return
    detachPromise(loadTimeline())
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
  const pipelineEffective = (pipeline?.pipeline_effective || docMeta.pipeline_effective || {})
  const analyticsRaw = (pipeline?.analytics_raw || docMeta.document_analytics_raw || {})
  const governanceRulePacks: string[] = (() => {
    if (Array.isArray(pipeline?.governance_rule_packs)) {
        return pipeline.governance_rule_packs;
    }
    else if (Array.isArray(docMeta.governance_rule_packs)) {
            return docMeta.governance_rule_packs;
        }
        else {
            return [];
        }
})()

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
        return '指定成员/组'
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
  /*
  const headerAction = (() => {
    if (activeView === 'chunks') {
      if (!chunkQuery) return null

      return (
        <IconButton
          label="娓呴櫎鎼滅储"
          variant="ghost"
          className="h-10 w-10 text-muted-foreground hover:text-foreground"
          onClick={() => setChunkQuery('')}
        >
          <X className="h-4 w-4" />
        </IconButton>
      )
    }

    return (
      <IconButton
        label="鍒锋柊鏃堕棿绾?"
        variant="ghost"
        className="h-10 w-10 text-muted-foreground hover:text-foreground"
        onClick={() => detachPromise(loadTimeline())}
        disabled={isLoadingTimeline}
      >
        {isLoadingTimeline ? (
          <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
        ) : (
          <RefreshCw className="h-4 w-4" />
        )}
      </IconButton>
    )
  })()
  let versionsListContent: ReactNode = null
  if (!isLoadingVersions && !versionsError) {
    if (versions?.items?.length) {
      versionsListContent = (
        <div className="space-y-2">
          {versions.items.map((v) => (
            <div
              key={v.pipeline_hash}
              className={cn(
                'flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-card p-3',
                v.active ? 'border-primary/30 bg-primary/5' : 'bg-card'
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
                  {v.last_chunk_at ? ` 路 鏇存柊 ${formatDate(v.last_chunk_at)}` : ''}
                </div>
              </div>

              <div className="flex flex-shrink-0 items-center gap-2">
                <IconButton
                  label="澶嶅埗鐗堟湰 hash"
                  variant="ghost"
                  className="h-9 w-9 text-muted-foreground hover:text-foreground"
                  onClick={() => detachPromise(copyToClipboard(v.pipeline_hash))}
                >
                  <Copy className="h-4 w-4" />
                </IconButton>

                {v.active ? (
                  <Button size="sm" variant="secondary" disabled>
                    宸叉縺娲?
                  </Button>
                ) : (
                  <>
                    <ConfirmDialog
                      title="鍒囨崲婵€娲荤増鏈紵"
                      description={
                        <>
                          灏嗘妸婵€娲荤増鏈垏鎹负 <span className="font-mono">{v.pipeline_hash.slice(0, 12)}鈥?/span>銆傝繖涓嶄細閲嶆柊瑙ｆ瀽/閲嶆柊鍚戦噺鍖栵紝鍙細褰卞搷妫€绱笌寮曠敤銆?
                        </>
                      }
                      confirmLabel="鍒囨崲"
                      cancelLabel="杩斿洖"
                      confirmVariant="default"
                      confirmDisabled={isVersionWorking}
                      onConfirm={() => detachPromise(handleActivateVersion(v.pipeline_hash))}
                    >
                      <Button size="sm" variant="outline" disabled={isVersionWorking}>
                        婵€娲?
                      </Button>
                    </ConfirmDialog>
                    <ConfirmDialog
                      title="鍒犻櫎璇ョ増鏈紵"
                      description={
                        <>
                          灏嗗垹闄ょ増鏈?<span className="font-mono">{v.pipeline_hash.slice(0, 12)}鈥?/span>銆傛敞鎰忥細褰撳墠婵€娲荤増鏈棤娉曞垹闄ゃ€?
                        </>
                      }
                      confirmLabel="鍒犻櫎"
                      cancelLabel="杩斿洖"
                      confirmVariant="destructive"
                      confirmDisabled={isVersionWorking}
                      onConfirm={() => detachPromise(handleDeleteVersion(v.pipeline_hash))}
                    >
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={isVersionWorking}
                        className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                      >
                        鍒犻櫎
                      </Button>
                    </ConfirmDialog>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )
    } else {
      versionsListContent = (
        <EmptyState
          icon={Hash}
          title="鏆傛棤鐗堟湰淇℃伅"
          description="褰撳墠鏂囨。杩樻病鏈夊彲鐢ㄧ殑 pipeline 鐗堟湰璁板綍锛堟垨灏氭湭鐢熸垚鍒囩墖锛夈€?
          className="min-h-[240px]"
        />
      )
    }
  }

  */
  const chunkRowVirtualizer = useVirtualizer({
    count: activeView === 'chunks' ? chunks.length : 0,
    getScrollElement: () => scrollParentRef.current,
    estimateSize: () => 220,
    overscan: 8,
    getItemKey: (idx) => chunks[idx]?.id ?? idx,
  })

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
        const textarea = globalThis.window.document.createElement('textarea')
        textarea.value = content
        textarea.style.position = 'fixed'
        textarea.style.left = '0'
        textarea.style.top = '0'
        textarea.style.opacity = '0'
        globalThis.window.document.body.appendChild(textarea)
        textarea.focus()
        textarea.select()
        const ok = globalThis.window.document.execCommand('copy')
        globalThis.window.document.body.removeChild(textarea)
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

  const [, saveAccessAction, isSavingAccess] = useActionState(async (_state: null, formData: FormData) => {
    if (!displayDoc?.id) return null

    const nextAccessMode = normalizeAccessMode(formData.get('access_mode'))
    const nextAccessGroupIds =
      nextAccessMode === 'partial_members' ? parseStringArrayField(formData.get('access_group_ids_json')) : []
    const nextAccessMembersText = String(formData.get('access_members_text') || '')

    try {
      const res = await documentApi.updateAccess(displayDoc.id, {
        mode: nextAccessMode,
        partial_member_list:
          nextAccessMode === 'partial_members' ? parseAccessMembers(nextAccessMembersText) : null,
        partial_group_list: nextAccessMode === 'partial_members' ? nextAccessGroupIds : null,
      })
      setAccessInfo(res)
      setAccessMode(res.mode)
      setAccessMembersText((res.partial_member_list || []).join('\n'))
      setAccessGroupIds((res.partial_group_list || []).map(String))
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
    }

    return null
  }, null)

  const handleVersionsDialogOpenChange = useCallback((next: boolean) => {
    setVersionsDialogOpen(next)
    if (next) {
      detachPromise(loadVersions())
    }
  }, [loadVersions])

  const handleAccessDialogOpenChange = useCallback((next: boolean) => {
    if (!next && isSavingAccess) return
    if (next) {
      setAccessMode(effectiveAccessMode)
      setAccessMembersText((accessInfo?.partial_member_list || []).join('\n'))
      setAccessGroupIds((accessInfo?.partial_group_list || []).map(String))
    }
    setAccessDialogOpen(next)
  }, [accessInfo?.partial_group_list, accessInfo?.partial_member_list, effectiveAccessMode, isSavingAccess])

  const handleVersionsRefresh = useCallback(() => {
    detachPromise(loadVersions())
  }, [loadVersions])

  const handleCopyText = useCallback((text: string) => {
    detachPromise(copyToClipboard(text))
  }, [copyToClipboard])

  const handleActivateVersionAction = useCallback((pipelineHash: string) => {
    detachPromise(handleActivateVersion(pipelineHash))
  }, [handleActivateVersion])

  const handleDeleteVersionAction = useCallback((pipelineHash: string) => {
    detachPromise(handleDeleteVersion(pipelineHash))
  }, [handleDeleteVersion])

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
                    onClick={() => detachPromise(copyToClipboard(String(viewingPipelineHash || '')))}
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
            {tagsEditing ? (
              <form action={saveTagsAction} className="space-y-4">
                <input type="hidden" name="tags_json" value={JSON.stringify(tagsDraft)} />
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
                    <Button type="button" variant="outline" size="sm" onClick={cancelEditTags} disabled={isSavingTags}>
                      取消
                    </Button>
                    <DocumentTagsSaveButton disabled={!canSaveTags} />
                  </div>
                </div>

                <div className="space-y-3">
                  <TagInput value={tagsDraft} onValueChange={setTagsDraft} disabled={isSavingTags} />

                  {tagsError ? (
                    <Alert variant="destructive">
                      <AlertTitle>保存失败</AlertTitle>
                      <AlertDescription>{tagsError}</AlertDescription>
                    </Alert>
                  ) : null}
                </div>
              </form>
            ) : (
              <>
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
                    <Button variant="outline" size="sm" className="gap-2" onClick={beginEditTags}>
                      <Pencil className="h-4 w-4" aria-hidden="true" />
                      编辑
                    </Button>
                  </div>
                </div>

                <div className="mt-4 space-y-3">
                  {optimisticTags.length ? (
                    <DocumentTags tags={optimisticTags} max={10} />
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
              </>
            )}
          </Panel>

          <Panel className="rounded-2xl">
            {lifecycleEditing ? (
              <form action={saveLifecycleAction}>
                <input type="hidden" name="publication_status" value={lifecyclePublicationStatusDraft} />

                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex items-start gap-3 min-w-0">
                    <div className="grid h-10 w-10 place-items-center rounded-2xl border border-border bg-warning/10 text-warning">
                      <Calendar className="h-5 w-5" aria-hidden="true" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-foreground">Lifecycle</div>
                      <div className="text-xs text-muted-foreground truncate">
                        owner / review_due / authority / supersedes（用于治理与检索偏好）
                      </div>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 justify-end">
                    <Button type="button" variant="outline" size="sm" onClick={cancelEditLifecycle} disabled={isSavingLifecycle}>
                      取消
                    </Button>
                    <DocumentLifecycleSaveButton disabled={!canSaveLifecycle} />
                  </div>
                </div>

                <div className="mt-4 space-y-3">
                  {lifecyclePermError ? (
                    <Alert variant="destructive">
                      <AlertTitle>权限检查失败</AlertTitle>
                      <AlertDescription>{lifecyclePermError}</AlertDescription>
                    </Alert>
                  ) : null}

                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <div className="space-y-1.5">
                      <div className="text-xs font-medium text-muted-foreground">publication_status</div>
                      <Select
                        value={lifecyclePublicationStatusDraft}
                        onValueChange={(v) =>
                          setLifecyclePublicationStatusDraft(v === 'draft' || v === 'deprecated' ? v : 'published')
                        }
                        disabled={isSavingLifecycle}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="published" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="published">published（默认参与检索）</SelectItem>
                          <SelectItem value="draft">draft（默认不参与检索）</SelectItem>
                          <SelectItem value="deprecated">deprecated（默认不参与检索）</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-1.5">
                      <div className="text-xs font-medium text-muted-foreground">owner</div>
                      <Input
                        name="lifecycle_owner"
                        value={lifecycleOwnerDraft}
                        onChange={(e) => setLifecycleOwnerDraft(e.target.value)}
                        placeholder="团队/负责人（建议使用 team alias，避免个人邮箱）"
                        disabled={isSavingLifecycle}
                      />
                    </div>

                    <div className="space-y-1.5">
                      <div className="text-xs font-medium text-muted-foreground">review_due_at</div>
                      <Input
                        name="review_due_at"
                        type="datetime-local"
                        value={lifecycleReviewDueDraft}
                        onChange={(e) => setLifecycleReviewDueDraft(e.target.value)}
                        disabled={isSavingLifecycle}
                      />
                    </div>

                    <div className="space-y-1.5">
                      <div className="text-xs font-medium text-muted-foreground">authority_level</div>
                      <Input
                        name="authority_level"
                        type="number"
                        min={0}
                        max={100}
                        step={1}
                        value={lifecycleAuthorityDraft}
                        onChange={(e) => setLifecycleAuthorityDraft(e.target.value)}
                        placeholder="0-100"
                        disabled={isSavingLifecycle}
                      />
                    </div>

                    <div className="space-y-1.5">
                      <div className="text-xs font-medium text-muted-foreground">supersedes_document_id</div>
                      <Input
                        name="supersedes_document_id"
                        value={lifecycleSupersedesDraft}
                        onChange={(e) => setLifecycleSupersedesDraft(e.target.value)}
                        placeholder="被替代的旧文档 UUID（可留空）"
                        disabled={isSavingLifecycle}
                      />
                    </div>
                  </div>

                  {lifecycleValidationError ? (
                    <Alert variant="destructive">
                      <AlertTitle>输入有误</AlertTitle>
                      <AlertDescription>{lifecycleValidationError}</AlertDescription>
                    </Alert>
                  ) : null}

                  {lifecycleError ? (
                    <Alert variant="destructive">
                      <AlertTitle>保存失败</AlertTitle>
                      <AlertDescription>{lifecycleError}</AlertDescription>
                    </Alert>
                  ) : null}
                </div>
              </form>
            ) : (
              <>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex items-start gap-3 min-w-0">
                    <div className="grid h-10 w-10 place-items-center rounded-2xl border border-border bg-warning/10 text-warning">
                      <Calendar className="h-5 w-5" aria-hidden="true" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-foreground">Lifecycle</div>
                      <div className="text-xs text-muted-foreground truncate">
                        owner / review_due / authority / supersedes（用于治理与检索偏好）
                      </div>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 justify-end">
                    <Button
                      variant="outline"
                      size="sm"
                      className="gap-2"
                      onClick={beginEditLifecycle}
                      disabled={lifecycleWritable === false || lifecycleWritable == null}
                      title={
                        lifecycleWritable === false
                          ? '只读：需要数据集编辑权限'
                          : lifecycleWritable == null
                            ? '权限确认中'
                            : undefined
                      }
                    >
                      <Pencil className="h-4 w-4" aria-hidden="true" />
                      编辑
                    </Button>
                  </div>
                </div>

                <div className="mt-4 space-y-3">
                  {lifecyclePermError ? (
                    <Alert variant="destructive">
                      <AlertTitle>权限检查失败</AlertTitle>
                      <AlertDescription>{lifecyclePermError}</AlertDescription>
                    </Alert>
                  ) : null}

                  <div className="space-y-1.5">
                    <TraceRow label="publication_status" value={String(displayDoc.publication_status || 'published')} />
                    <TraceRow label="lifecycle_owner" value={String(displayDoc.lifecycle_owner || '-')} />
                    <TraceRow
                      label="review_due_at"
                      value={
                        displayDoc.review_due_at
                          ? new Date(String(displayDoc.review_due_at)).toLocaleString('zh-CN')
                          : '-'
                      }
                    />
                    <TraceRow
                      label="authority_level"
                      value={displayDoc.authority_level == null ? '-' : String(displayDoc.authority_level)}
                      mono
                    />
                    <TraceRow label="supersedes_document_id" value={String(displayDoc.supersedes_document_id || '-')} mono />

                    {!displayDoc.lifecycle_owner && !displayDoc.review_due_at && displayDoc.authority_level == null && !displayDoc.supersedes_document_id ? (
                      <div className="text-xs text-muted-foreground">暂无 lifecycle 信息（可用于 stale 报表、检索偏好与治理审计）</div>
                    ) : null}
                  </div>

                  {lifecycleError ? (
                    <Alert variant="destructive">
                      <AlertTitle>保存失败</AlertTitle>
                      <AlertDescription>{lifecycleError}</AlertDescription>
                    </Alert>
                  ) : null}
                </div>
              </>
            )}
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
                  id={chunksTabId}
                  role="tab"
                  aria-controls={chunksPanelId}
                  aria-selected={activeView === 'chunks'}
                  tabIndex={activeView === 'chunks' ? 0 : -1}
                  className={cn(
                    "inline-flex h-8 items-center justify-center whitespace-nowrap rounded-sm px-3 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none",
                    activeView === "chunks" ? "bg-background text-foreground shadow-sm" : "hover:text-foreground"
                  )}
                  onClick={() => setActiveView("chunks")}
                  onKeyDown={handleViewTabKeyDown}
                >
                  切片
                </button>
                <button
                  type="button"
                  id={timelineTabId}
                  role="tab"
                  aria-controls={timelinePanelId}
                  aria-selected={activeView === 'timeline'}
                  tabIndex={activeView === 'timeline' ? 0 : -1}
                  className={cn(
                    "inline-flex h-8 items-center justify-center whitespace-nowrap rounded-sm px-3 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none",
                    activeView === "timeline" ? "bg-background text-foreground shadow-sm" : "hover:text-foreground"
                  )}
                  onClick={() => setActiveView("timeline")}
                  onKeyDown={handleViewTabKeyDown}
                >
                  时间线
                </button>
              </div>

              {null}
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
                  onClick={() => detachPromise(loadTimeline())}
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

            <div
              ref={scrollParentRef}
              id={activeView === 'chunks' ? chunksPanelId : timelinePanelId}
              role="tabpanel"
              aria-labelledby={activeView === 'chunks' ? chunksTabId : timelineTabId}
              className="h-full overflow-y-auto overscroll-contain no-scrollbar p-4"
            >
              {(() => {
    if (activeView === "chunks") {
        return ((() => {
            if ((isLoadingDoc && !detail) || (isLoadingChunks && chunks.length === 0)) {
                return (<div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
                    <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none"/>
                    <p className="text-sm">{messages.documents.loadingChunks}</p>
                  </div>);
            }
            else if (loadError && chunks.length === 0) {
                    return (<div className="mx-auto max-w-2xl py-10">
                    <Alert variant="destructive">
                      <AlertTitle>加载失败</AlertTitle>
                      <AlertDescription>{loadError}</AlertDescription>
                    </Alert>
                    <div className="mt-4 flex items-center justify-end gap-2">
                      <Button variant="outline" onClick={() => {
                            detachPromise(loadDetail());
                            detachPromise(loadVersions());
                            detachPromise(reloadChunks());
                        }}>
                        {messages.common.retry}
                      </Button>
                      <Button variant="secondary" onClick={() => setOpen(false)}>
                        {messages.common.close}
                      </Button>
                    </div>
                  </div>);
                }
                else if (chunksTotal === 0 && !isSearching) {
                        return (<EmptyState icon={FileText} title={messages.documents.emptyChunks} description="该文档暂未生成可用切片，或后端未返回切片内容。" className="min-h-[320px]"/>);
                    }
                    else if (chunksTotal === 0 && isSearching) {
                            return (<EmptyState icon={Search} title="未找到匹配切片" description={<span>尝试更换关键词，或清空筛选条件。</span>} className="min-h-[320px]">
	                    <Button variant="outline" onClick={() => setChunkQuery("")}>
	                      清空筛选
	                    </Button>
	                  </EmptyState>);
                        }
                        else {
                            return (<div className="pb-6 space-y-3">
	                    {chunkError && chunks.length > 0 ? (<Alert variant="destructive">
	                        <AlertTitle>加载切片失败</AlertTitle>
	                        <AlertDescription>{chunkError}</AlertDescription>
	                      </Alert>) : null}
	
	                    <div role="list" aria-label="文档切片列表" style={{
                                    height: `${chunkRowVirtualizer.getTotalSize()}px`,
                                    width: '100%',
                                    position: 'relative',
                                }}>
	                      {chunkRowVirtualizer.getVirtualItems().map((virtualRow) => {
                                    const chunk = chunks[virtualRow.index];
                                    if (!chunk)
                                        return null;
                                    return (<div key={virtualRow.key} data-index={virtualRow.index} ref={chunkRowVirtualizer.measureElement} role="listitem" style={{
                                            position: 'absolute',
                                            top: 0,
                                            left: 0,
                                            width: '100%',
                                            transform: `translateY(${virtualRow.start}px)`,
                                        }} className="pb-3">
	                            <div className={cn("group rounded-xl border border-border/60 bg-card p-4 transition-colors", "hover:border-primary/25 hover:shadow-soft/30", chunk.disabled_at ? "opacity-70" : null)}>
	                              <div className="flex items-start justify-between gap-3">
	                                <div className="flex flex-wrap items-center gap-2 text-xs">
	                                  <span className="rounded-full border border-border/60 bg-muted px-2 py-0.5 font-mono font-medium text-muted-foreground">
	                                    #{chunk.chunk_index}
	                                  </span>
	                                  {typeof chunk.page_number === "number" ? (<span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-muted-foreground">
	                                      P.{chunk.page_number}
	                                    </span>) : null}
	                                  <span className="text-muted-foreground">{(chunk.content || "").length} chars</span>
	                                  {chunk.disabled_at ? (<span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-muted-foreground">
	                                      disabled
	                                    </span>) : null}
	                                </div>
	                                <div className="flex items-center gap-1">
	                                  <IconButton label={canMutateChunks ? "编辑切片" : "仅当前激活版本可编辑"} variant="ghost" className="h-9 w-9 text-muted-foreground hover:text-foreground" onClick={() => beginEditChunk(chunk)} disabled={!canMutateChunks || chunkOpWorkingId === chunk.id}>
	                                    <Pencil className="h-4 w-4"/>
	                                  </IconButton>
	                                  <IconButton label={chunk.disabled_at ? "启用切片" : "禁用切片"} variant="ghost" className="h-9 w-9 text-muted-foreground hover:text-foreground" onClick={() => detachPromise(toggleChunkDisabled(chunk))} disabled={!canMutateChunks || chunkOpWorkingId === chunk.id}>
	                                    {chunk.disabled_at ? <CheckCircle2 className="h-4 w-4"/> : <Ban className="h-4 w-4"/>}
	                                  </IconButton>
	                                  <IconButton label={chunk.disabled_at ? "禁用切片不能 re-embed" : "重新嵌入切片"} variant="ghost" className="h-9 w-9 text-muted-foreground hover:text-foreground" onClick={() => detachPromise(reembedChunk(chunk))} disabled={!canMutateChunks || Boolean(chunk.disabled_at) || chunkOpWorkingId === chunk.id}>
	                                    <RefreshCw className="h-4 w-4"/>
	                                  </IconButton>
	                                  <IconButton label="复制切片内容" variant="ghost" className="h-9 w-9 text-muted-foreground hover:text-foreground" onClick={() => detachPromise(copyToClipboard(chunk.content))} disabled={chunkOpWorkingId === chunk.id}>
	                                    <Copy className="h-4 w-4"/>
	                                  </IconButton>
	                                </div>
	                              </div>
	
	                              {editingChunkId === chunk.id ? (<div className="mt-3 space-y-2">
	                                  <Textarea value={editingChunkContent} onChange={(e) => setEditingChunkContent(e.target.value)} className="min-h-[140px] font-mono text-xs" disabled={!canMutateChunks || chunkOpWorkingId === chunk.id}/>
	                                  <div className="flex items-center justify-end gap-2">
	                                    <Button type="button" variant="outline" size="sm" onClick={cancelEditChunk} disabled={chunkOpWorkingId === chunk.id}>
	                                      {messages.common.cancel}
	                                    </Button>
	                                    <Button type="button" size="sm" onClick={() => detachPromise(saveEditChunk())} disabled={!canMutateChunks || chunkOpWorkingId === chunk.id} className="gap-2">
	                                      {chunkOpWorkingId === chunk.id ? (<Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none"/>) : (<Save className="h-4 w-4"/>)}
	                                      {messages.common.save}
	                                    </Button>
	                                  </div>
	                                </div>) : (<div className="mt-2 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground/90">
	                                  {highlightText(chunk.content || "", chunkQuery)}
	                                </div>)}
	                            </div>
	                          </div>);
                                })}
	                    </div>
	
	                    {canLoadMoreChunks ? (<div className="flex justify-center pt-2">
	                        <Button variant="outline" onClick={() => detachPromise(loadMoreChunks())} disabled={isLoadingChunks} className="gap-2">
	                          {isLoadingChunks ? (<Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none"/>) : null}
	                          加载更多
	                        </Button>
	                      </div>) : null}
	                  </div>);
                        }
        })());
    }
    else if (isLoadingTimeline && timelineItems.length === 0) {
            return (<div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
	                  <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none"/>
                  <p className="text-sm">{messages.documents.loadingTimeline}</p>
                </div>);
        }
        else if ((timelineError || docError) && timelineItems.length === 0) {
                return (<div className="mx-auto max-w-2xl py-10">
                  <Alert variant="destructive">
                    <AlertTitle>加载失败</AlertTitle>
                    <AlertDescription>{timelineError || docError}</AlertDescription>
                  </Alert>
                  <div className="mt-4 flex items-center justify-end gap-2">
                    <Button variant="outline" onClick={() => detachPromise(loadTimeline())}>
                      {messages.common.retry}
                    </Button>
                    <Button variant="secondary" onClick={() => setOpen(false)}>
                      {messages.common.close}
                    </Button>
                  </div>
                </div>);
            }
            else if (timelineItems.length === 0) {
                    return (<EmptyState icon={Calendar} title={messages.documents.emptyTimeline} description="该文档暂未产生可回溯的事件记录（或审计未启用）。" className="min-h-[320px]"/>);
                }
                else {
                    return (<div className="pb-6 space-y-3">
	                  {timelineError ? (<Alert variant="destructive">
	                      <AlertTitle>加载时间线失败</AlertTitle>
	                      <AlertDescription>{timelineError}</AlertDescription>
	                    </Alert>) : null}
	
	                  <div role="list" aria-label="文档时间线" style={{
                            height: `${timelineRowVirtualizer.getTotalSize()}px`,
                            width: '100%',
                            position: 'relative',
                        }}>
	                    {timelineRowVirtualizer.getVirtualItems().map((virtualRow) => {
                            const ev = timelineItems[virtualRow.index];
                            if (!ev)
                                return null;
                            const detailPairs = Object.entries(ev.details || {}).slice(0, 12);
                            const hasDetails = detailPairs.length > 0;
                            return (<div key={virtualRow.key} data-index={virtualRow.index} ref={timelineRowVirtualizer.measureElement} role="listitem" style={{
                                    position: 'absolute',
                                    top: 0,
                                    left: 0,
                                    width: '100%',
                                    transform: `translateY(${virtualRow.start}px)`,
                                }} className="pb-3">
	                          <div className={cn("group rounded-xl border border-border/60 bg-card p-4 transition-colors", "hover:border-primary/25 hover:shadow-soft/30")}>
	                            <div className="flex items-start justify-between gap-3">
	                              <div className="min-w-0">
	                                <div className="flex flex-wrap items-center gap-2">
	                                  <span className="rounded-full border border-border/60 bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground">
	                                    {formatDate(ev.created_at)}
	                                  </span>
	                                  <span className="truncate font-mono text-xs text-foreground/90">{ev.action}</span>
	                                  {ev.source === "synthetic" ? (<span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-xs text-muted-foreground">
	                                      synthetic
	                                    </span>) : null}
	                                </div>
	
	                                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
	                                  {ev.stage ? <span>stage: {ev.stage}</span> : null}
	                                  {ev.status ? <span>status: {ev.status}</span> : null}
	                                  {typeof ev.progress === "number" ? <span>progress: {ev.progress}%</span> : null}
	                                  {ev.request_id ? (<span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 font-mono">
	                                      req: {ev.request_id}
	                                    </span>) : null}
	                                  {ev.actor_id ? (<span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 font-mono">
	                                      by: {ev.actor_id}
	                                    </span>) : null}
	                                </div>
	                              </div>
	
	                              <IconButton label="复制事件信息" variant="ghost" className="h-9 w-9 text-muted-foreground hover:text-foreground" onClick={() => detachPromise(copyToClipboard(JSON.stringify({
                                    id: ev.id,
                                    action: ev.action,
                                    created_at: ev.created_at,
                                    stage: ev.stage,
                                    status: ev.status,
                                    progress: ev.progress,
                                    request_id: ev.request_id,
                                    actor_id: ev.actor_id,
                                    details: ev.details,
                                }, null, 2)))}>
	                                <Copy className="h-4 w-4"/>
	                              </IconButton>
	                            </div>
	
	                            {hasDetails ? (<div className="mt-3 flex flex-wrap gap-2">
	                                {detailPairs.map(([k, v]) => (<span key={`${ev.id}:${k}`} className="rounded-md border border-border/60 bg-muted/40 px-2 py-1 font-mono text-[11px] text-muted-foreground" title={`${k}: ${String(v)}`}>
	                                    {k}: {String(v)}
	                                  </span>))}
	                              </div>) : null}
	                          </div>
	                        </div>);
                        })}
	                  </div>
	                </div>);
                }
})()}
            </div>
          </Panel>
        </main>

        {/* Footer */}
        <footer className="border-t border-border bg-muted/20 px-6 py-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-col gap-2 sm:flex-row">
              <DocumentVersionsDialog
                open={versionsDialogOpen}
                onOpenChange={handleVersionsDialogOpenChange}
                activePipelineHash={versions?.active_pipeline_hash}
                versions={versions}
                isLoading={isLoadingVersions}
                error={versionsError}
                isWorking={isVersionWorking}
                onRefresh={handleVersionsRefresh}
                onCopy={handleCopyText}
                onActivate={handleActivateVersionAction}
                onDelete={handleDeleteVersionAction}
              />

              <DocumentAccessDialog
                open={accessDialogOpen}
                onOpenChange={handleAccessDialogOpenChange}
                ownerId={displayDoc.owner_id}
                accessMode={accessMode}
                onAccessModeChange={setAccessMode}
                accessGroupIds={accessGroupIds}
                onAccessGroupIdsChange={setAccessGroupIds}
                accessMembersText={accessMembersText}
                onAccessMembersTextChange={setAccessMembersText}
                action={saveAccessAction}
              />

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
                onConfirm={() => detachPromise(handleDeleteKG())}
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
