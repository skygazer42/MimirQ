/**
 * 文档详情对话框 - 展示最终切片结果
 */
'use client'

import { startTransition, useActionState, useCallback, useEffect, useId, useMemo, useOptimistic, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react'
import { useFormStatus } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Calendar, Database, Download, Eye, FileType, Hash, Loader2, Shield } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { DocumentAccessDialog } from '@/components/document-detail-dialog/document-access-dialog'
import { DocumentDetailActivityPanel } from '@/components/document-detail-dialog/document-detail-activity-panel'
import { DocumentDetailLifecyclePanel } from '@/components/document-detail-dialog/document-detail-lifecycle-panel'
import { DocumentDetailSummaryCards } from '@/components/document-detail-dialog/document-detail-summary-cards'
import { DocumentDetailTagsPanel } from '@/components/document-detail-dialog/document-detail-tags-panel'
import { DocumentVersionsDialog } from '@/components/document-detail-dialog/document-versions-dialog'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { IconButton } from '@/components/ui/icon-button'
import { StatusBadge, type StatusBadgeStatus } from '@/components/ui/status-badge'
import { documentApi, kgApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { buildTagsPatch, getUserTagsFromDocument, normalizeTags } from '@/lib/document-user-tags'
import { getParserLabel } from '@/lib/parser-options'
import { queryKeys } from '@/lib/query-keys'
import { formatDate, formatFileSize, detachPromise } from '@/lib/utils'
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
  trigger?: ReactNode
}

const EMPTY_CHUNKS: DocumentChunk[] = []
const ACTIVE_PIPELINE_VALUE = '__active__'
const CHUNK_PAGE_SIZE = 200
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
type SaveActionState = 'idle' | 'skipped' | 'saved' | 'failed'
type DocumentPublicationStatus = 'draft' | 'published' | 'deprecated'
type LifecycleDraftValues = {
  publicationStatus: DocumentPublicationStatus
  owner: string
  reviewDueAt: string
  authorityLevel: string
  supersedesDocumentId: string
}
type LifecycleValidationKey =
  | 'validation.supersedesUuid'
  | 'validation.authorityInteger'
  | 'validation.authorityRange'
  | 'validation.reviewDueAt'
type AccessModeFormValue = FormDataEntryValue | string | null | undefined

function formString(value: FormDataEntryValue | string | null | undefined, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function safeFilename(value: string | null | undefined, fallback: string): string {
  const raw = String(value || '').trim() || fallback
  return raw.replace(/[^\w.-]+/g, '_').slice(0, 96) || fallback
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

function toDatetimeLocalValue(value: string | null | undefined): string {
  const raw = formString(value).trim()
  if (!raw) return ''
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function normalizeAccessMode(value: AccessModeFormValue): DocumentAccessMode {
  const normalized = formString(value).trim()
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
    parsed = JSON.parse(formString(value, '[]'))
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
  const normalized = formString(value).trim()
  return normalized === 'draft' || normalized === 'deprecated' ? normalized : 'published'
}

function getLifecycleValidationError(
  values: Pick<LifecycleDraftValues, 'authorityLevel' | 'reviewDueAt' | 'supersedesDocumentId'>,
  translate: (key: LifecycleValidationKey) => string
) {
  const sup = values.supersedesDocumentId.trim()
  if (sup && !UUID_RE.test(sup)) return translate('validation.supersedesUuid')

  const auth = values.authorityLevel.trim()
  if (auth) {
    const n = Number.parseInt(auth, 10)
    if (!Number.isFinite(n)) return translate('validation.authorityInteger')
    if (n < 0 || n > 100) return translate('validation.authorityRange')
  }

  const due = values.reviewDueAt.trim()
  if (due) {
    const d = new Date(due)
    if (Number.isNaN(d.getTime())) return translate('validation.reviewDueAt')
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

function DocumentSaveButton({ disabled }: Readonly<{ disabled: boolean }>) {
  const commonT = useTranslations('Common')
  const { pending } = useFormStatus()

  return (
    <Button size="sm" type="submit" disabled={disabled || pending}>
      {pending ? (
        <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
      ) : null}
      {commonT('save')}
    </Button>
  )
}

export function DocumentDetailDialog({ document: initialDocument, trigger }: Readonly<DocumentDetailDialogProps>) {
  const commonT = useTranslations('Common')
  const t = useTranslations('DocumentDetailDialog')
  const permissionAlertTitle = t('alerts.permissionCheckFailedTitle')
  const validationAlertTitle = t('alerts.validationFailedTitle')
  const viewTabsId = useId()
  const chunksTabId = `${viewTabsId}-chunks-tab`
  const timelineTabId = `${viewTabsId}-timeline-tab`
  const chunksPanelId = `${viewTabsId}-chunks-panel`
  const timelinePanelId = `${viewTabsId}-timeline-panel`
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [activeView, setActiveView] = useState<'chunks' | 'timeline'>('chunks')

  const scrollParentRef = useRef<HTMLDivElement>(null)

  const [chunks, setChunks] = useState<DocumentChunk[]>(EMPTY_CHUNKS)
  const [chunksTotal, setChunksTotal] = useState(0)
  const [isLoadingChunks, setIsLoadingChunks] = useState(false)
  const [chunkError, setChunkError] = useState<string | null>(null)
  const [versionsDialogOpen, setVersionsDialogOpen] = useState(false)
  const [isVersionWorking, setIsVersionWorking] = useState(false)
  const [viewPipelineHash, setViewPipelineHash] = useState<string>(ACTIVE_PIPELINE_VALUE)

  const [isKgWorking, setIsKgWorking] = useState(false)
  const [isCleanDocxDownloading, setIsCleanDocxDownloading] = useState(false)
  const [chunkQuery, setChunkQuery] = useState('')
  const [editingChunkId, setEditingChunkId] = useState<string | null>(null)
  const [editingChunkContent, setEditingChunkContent] = useState<string>('')
  const [chunkOpWorkingId, setChunkOpWorkingId] = useState<string | null>(null)
  const [accessDialogOpen, setAccessDialogOpen] = useState(false)
  const [accessMode, setAccessMode] = useState<DocumentAccessMode>('inherit')

  const [lifecycleEditing, setLifecycleEditing] = useState(false)
  const [lifecyclePublicationStatusDraft, setLifecyclePublicationStatusDraft] = useState<
    'draft' | 'published' | 'deprecated'
  >('published')
  const [lifecycleOwnerDraft, setLifecycleOwnerDraft] = useState('')
  const [lifecycleReviewDueDraft, setLifecycleReviewDueDraft] = useState('')
  const [lifecycleAuthorityDraft, setLifecycleAuthorityDraft] = useState('')
  const [lifecycleSupersedesDraft, setLifecycleSupersedesDraft] = useState('')
  const [lifecycleError, setLifecycleError] = useState<string | null>(null)

  const detailQueryKey = queryKeys.documents.detail(initialDocument.id)
  const accessQueryKey = queryKeys.documents.access(initialDocument.id)
  const versionsQueryKey = queryKeys.documents.versions(initialDocument.id)
  const timelineQueryParams = { limit: 200 } as const
  const timelineQueryKey = queryKeys.documents.timeline(initialDocument.id, timelineQueryParams)

  const detailQuery = useQuery({
    queryKey: detailQueryKey,
    queryFn: () => documentApi.get(initialDocument.id),
    enabled: open,
  })

  const accessQuery = useQuery<DocumentAccessInfo | null>({
    queryKey: accessQueryKey,
    queryFn: async () => {
      try {
        return await documentApi.getAccess(initialDocument.id)
      } catch (err) {
        console.warn('Load document access error:', err)
        return null
      }
    },
    enabled: open,
  })

  const lifecyclePermissionQuery = useQuery({
    queryKey: ['documents', 'lifecycle-permission', initialDocument.id] as const,
    queryFn: async () => {
      try {
        await documentApi.getLifecycleMetadata(initialDocument.id)
        return { writable: true as boolean | null, error: null as string | null }
      } catch (err) {
        const status =
          typeof err === 'object' && err !== null && 'response' in err
            ? (err as { response?: { status?: number } }).response?.status
            : undefined
        if (status === 403) return { writable: false as boolean | null, error: null as string | null }
        return {
          writable: null as boolean | null,
          error: formatApiError(err, t('errors.lifecyclePermissionCheckUnknown')),
        }
      }
    },
    enabled: open,
  })

  const versionsQuery = useQuery<DocumentVersionList>({
    queryKey: versionsQueryKey,
    queryFn: () => documentApi.listVersions(initialDocument.id),
    enabled: open,
  })

  const timelineQuery = useQuery<DocumentTimelineResponse>({
    queryKey: timelineQueryKey,
    queryFn: () => documentApi.getTimeline(initialDocument.id, timelineQueryParams),
    enabled: open && activeView === 'timeline',
  })

  const detail = detailQuery.data ?? null
  const accessInfo = accessQuery.data ?? null
  const versions = versionsQuery.data ?? null
  const timeline = timelineQuery.data ?? null
  const lifecycleWritable = lifecyclePermissionQuery.data?.writable ?? null
  const lifecyclePermError = lifecyclePermissionQuery.data?.error ?? null
  const isLoadingDoc = open && (detailQuery.isLoading || accessQuery.isLoading || lifecyclePermissionQuery.isLoading)
  const isLoadingVersions = versionsQuery.isFetching
  const isLoadingTimeline = timelineQuery.isFetching
  const docError = detailQuery.error ? formatApiError(detailQuery.error, t('errors.loadDetailFailed')) : null
  const versionsError = versionsQuery.error ? formatApiError(versionsQuery.error, t('errors.loadVersionsFailed')) : null
  const timelineError = timelineQuery.error ? formatApiError(timelineQuery.error, t('errors.loadTimelineFailed')) : null

  const persistedTags = useMemo(() => getUserTagsFromDocument(detail || initialDocument), [detail, initialDocument])
  const [optimisticTags, applyOptimisticTags] = useOptimistic(
    persistedTags,
    (_currentTags, nextTags: string[]) => normalizeTags(nextTags)
  )
  const [tagsEditing, setTagsEditing] = useState(false)
  const [tagsDraft, setTagsDraft] = useState<string[]>([])
  const [tagsError, setTagsError] = useState<string | null>(null)

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
      case 'Home':
        event.preventDefault()
        focusViewTab('chunks')
        break
      case 'ArrowRight':
      case 'ArrowDown':
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

  const [, saveTagsAction, isSavingTags] = useActionState(async (_state: SaveActionState, formData: FormData): Promise<SaveActionState> => {
    if (!tagsEditing) return 'skipped'

    let parsedTags: unknown = []
    try {
      parsedTags = JSON.parse(formString(formData.get('tags_json'), '[]'))
    } catch {
      parsedTags = []
    }

    const nextTags = normalizeTags(parsedTags)
    if (nextTags.length === persistedTags.length && nextTags.every((tag, index) => tag === persistedTags[index])) {
      return 'skipped'
    }

    setTagsError(null)
    startTransition(() => {
      applyOptimisticTags(nextTags)
    })
    setTagsEditing(false)
    setTagsDraft([])

    try {
      const updated = await documentApi.patchUserMetadata(initialDocument.id, buildTagsPatch(nextTags))
      queryClient.setQueryData(detailQueryKey, updated)
      toast.success(t("toasts.tagsUpdated"))
      return 'saved'
    } catch (err) {
      console.error('Update document tags failed:', err)
      const msg = formatApiError(err, t('errors.saveTagsFailed'))
      setTagsError(msg)
      setTagsDraft(nextTags)
      setTagsEditing(true)
      toast.error(msg)
      return 'failed'
    }
  }, 'idle' as SaveActionState)

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
      toast.success(t('toasts.chunkSaved'))
    } catch (err) {
      console.error('Update chunk failed:', err)
      toast.error(formatApiError(err, t('errors.saveChunkFailed')))
    } finally {
      setChunkOpWorkingId((prev) => (prev === chunkId ? null : prev))
    }
  }, [canMutateChunks, editingChunkContent, editingChunkId, initialDocument.id, t])

  const toggleChunkDisabled = useCallback(
    async (chunk: DocumentChunk) => {
      if (!canMutateChunks) return
      setChunkOpWorkingId(chunk.id)
      try {
        const updated = chunk.disabled_at
          ? await documentApi.enableChunk(initialDocument.id, chunk.id)
          : await documentApi.disableChunk(initialDocument.id, chunk.id)
        setChunks((prev) => prev.map((c) => (c.id === chunk.id ? updated : c)))
        toast.success(chunk.disabled_at ? t('toasts.chunkEnabled') : t('toasts.chunkDisabled'))
      } catch (err) {
        console.error('Toggle chunk disabled failed:', err)
        toast.error(formatApiError(err, t('errors.chunkOperationFailed')))
      } finally {
        setChunkOpWorkingId((prev) => (prev === chunk.id ? null : prev))
      }
    },
    [canMutateChunks, initialDocument.id, t]
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
        toast.success(t('toasts.chunkReembedded', { count: res.reembedded }))
      } catch (err) {
        console.error('Re-embed chunk failed:', err)
        toast.error(formatApiError(err, t('errors.reembedFailed')))
      } finally {
        setChunkOpWorkingId((prev) => (prev === chunk.id ? null : prev))
      }
    },
    [canMutateChunks, initialDocument.id, t]
  )
  const [accessMembersText, setAccessMembersText] = useState('')
  const [accessGroupIds, setAccessGroupIds] = useState<string[]>([])

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
    () => getLifecycleValidationError(lifecycleDraftValues, t),
    [lifecycleDraftValues, t]
  )

  const lifecycleHasChanges = useMemo(
    () => hasLifecycleChanges(detail || initialDocument, lifecycleDraftValues),
    [detail, initialDocument, lifecycleDraftValues]
  )

  const [, saveLifecycleAction, isSavingLifecycle] = useActionState(async (_state: SaveActionState, formData: FormData): Promise<SaveActionState> => {
    if (!lifecycleEditing) return 'skipped'

    const nextValues: LifecycleDraftValues = {
      publicationStatus: normalizePublicationStatus(formData.get('publication_status')),
      owner: formString(formData.get('lifecycle_owner')).trim(),
      reviewDueAt: formString(formData.get('review_due_at')).trim(),
      authorityLevel: formString(formData.get('authority_level')).trim(),
      supersedesDocumentId: formString(formData.get('supersedes_document_id')).trim(),
    }

    const validationError = getLifecycleValidationError(nextValues, t)
    if (validationError) {
      setLifecycleError(validationError)
      return 'failed'
    }

    const currentDoc = detail || initialDocument
    if (!hasLifecycleChanges(currentDoc, nextValues)) {
      return 'skipped'
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
      toast.success(t('toasts.lifecycleUpdated'))
      cancelEditLifecycle()
      await Promise.all([
        detailQuery.refetch(),
        accessQuery.refetch(),
        lifecyclePermissionQuery.refetch(),
      ])
      return 'saved'
    } catch (err) {
      console.error('Update document lifecycle metadata failed:', err)
      const msg = formatApiError(err, t('errors.saveLifecycleFailed'))
      setLifecycleError(msg)
      toast.error(msg)
      return 'failed'
    }
  }, 'idle' as SaveActionState)

  const canSaveLifecycle = lifecycleEditing && !isSavingLifecycle && !lifecycleValidationError && lifecycleHasChanges

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
    } catch (err) {
      console.error('Load document chunks error:', err)
      setChunkError(formatApiError(err, t('errors.loadChunksFailed')))
    } finally {
      setIsLoadingChunks(false)
    }
  }, [fetchChunksPage, t])

  const loadMoreChunks = useCallback(async () => {
    if (isLoadingChunks) return
    if (chunks.length >= chunksTotal) return
    setIsLoadingChunks(true)
    setChunkError(null)
    try {
      const res = await fetchChunksPage(chunks.length)
      setChunks((prev) => [...prev, ...(res.items || [])])
      setChunksTotal(Number(res.total || 0))
    } catch (err) {
      console.error('Load more chunks error:', err)
      setChunkError(formatApiError(err, t('errors.loadMoreChunksFailed')))
    } finally {
      setIsLoadingChunks(false)
    }
  }, [chunks.length, chunksTotal, fetchChunksPage, isLoadingChunks, t])

  useEffect(() => {
    if (!open) return
    setActiveView('chunks')
  }, [open])

  useEffect(() => {
    if (!open) return
    if (activeView !== 'chunks') return
    const handle = globalThis.window.setTimeout(() => {
      detachPromise(reloadChunks())
    }, chunkQuery.trim() ? 250 : 0)
    return () => globalThis.window.clearTimeout(handle)
  }, [open, activeView, chunkQuery, viewPipelineHash, reloadChunks])
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
  const requestedParserBackend = String(
    pipeline?.parser_backend_requested || docMeta?.parser_backend_requested || '-'
  )
  const pipelineEffective = (pipeline?.pipeline_effective || docMeta.pipeline_effective || {})
  const analyticsRaw = (pipeline?.analytics_raw || docMeta.document_analytics_raw || {})
  const governanceRulePacks: string[] = (() => {
    if (Array.isArray(pipeline?.governance_rule_packs)) {
      return pipeline.governance_rule_packs
    }
    if (Array.isArray(docMeta.governance_rule_packs)) {
      return docMeta.governance_rule_packs
    }
    return []
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
        return t("accessModes.inherit")
      case 'only_me':
        return t('accessModes.onlyMe')
      case 'partial_members':
        return t('accessModes.partialMembers')
      case 'all_team_members':
        return t('accessModes.allTeamMembers')
      default:
        return String(effectiveAccessMode)
    }
  }, [effectiveAccessMode, t])

  const isSearching = chunkQuery.trim().length > 0
  const canLoadMoreChunks = chunks.length < chunksTotal
  const loadError = docError || chunkError
  const timelineItems: DocumentTimelineItem[] = timeline?.items || []
  const timelineTotal = Number(timeline?.total || timelineItems.length)
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
      if (!navigator.clipboard?.writeText) {
        throw new Error('Clipboard API unavailable')
      }
      await navigator.clipboard.writeText(content)
      toast.success(t("toasts.copySuccess"))
    } catch (err) {
      console.error('Copy failed:', err)
      toast.error(t("errors.copyFailed"))
    }
  }, [t])

  const handleActivateVersion = useCallback(
    async (pipelineHash: string) => {
      const ph = String(pipelineHash || '').trim()
      if (!ph) return

      setIsVersionWorking(true)
      try {
        await documentApi.activateVersion(initialDocument.id, ph)
        toast.success(t('toasts.versionActivated'))
        setViewPipelineHash(ACTIVE_PIPELINE_VALUE)
        await Promise.all([
          detailQuery.refetch(),
          accessQuery.refetch(),
          lifecyclePermissionQuery.refetch(),
          versionsQuery.refetch(),
        ])
        await reloadChunks()
      } catch (err) {
        console.error('Activate document version failed:', err)
        toast.error(formatApiError(err, t('errors.activateVersionFailed')))
      } finally {
        setIsVersionWorking(false)
      }
    },
    [accessQuery, detailQuery, initialDocument.id, lifecyclePermissionQuery, reloadChunks, t, versionsQuery]
  )

  const handleDeleteVersion = useCallback(
    async (pipelineHash: string) => {
      const ph = String(pipelineHash || '').trim()
      if (!ph) return

      setIsVersionWorking(true)
      try {
        await documentApi.deleteVersion(initialDocument.id, ph)
        toast.success(t('toasts.versionDeleted'))
        // If the user was viewing this version, fallback to active.
        if (viewPipelineHash === ph) {
          setViewPipelineHash(ACTIVE_PIPELINE_VALUE)
        }
        await Promise.all([
          versionsQuery.refetch(),
          detailQuery.refetch(),
          accessQuery.refetch(),
          lifecyclePermissionQuery.refetch(),
        ])
        await reloadChunks()
      } catch (err) {
        console.error('Delete document version failed:', err)
        toast.error(formatApiError(err, t('errors.deleteVersionFailed')))
      } finally {
        setIsVersionWorking(false)
      }
    },
    [accessQuery, detailQuery, initialDocument.id, lifecyclePermissionQuery, reloadChunks, t, versionsQuery, viewPipelineHash]
  )

  const handleExtractKG = async () => {
    if (!canRunKg) return
    setIsKgWorking(true)
    try {
      await kgApi.extract(displayDoc.id, { async: true, replace_existing: true, prune_orphan_entities: true })
      toast.success(t('toasts.kgExtractStarted'))
    } catch (err) {
      console.error('KG extract failed:', err)
      toast.error(formatApiError(err, t('errors.kgExtractFailed')))
    } finally {
      setIsKgWorking(false)
    }
  }

  const handleDeleteKG = async () => {
    if (isKgWorking) return
    setIsKgWorking(true)
    try {
      const res = await kgApi.deleteDocumentKG(displayDoc.id, { prune_orphan_entities: true })
      toast.success(t('toasts.kgDeleted', { events: res.events_deleted, entities: res.entities_pruned }))
    } catch (err) {
      console.error('KG delete failed:', err)
      toast.error(formatApiError(err, t('errors.kgDeleteFailed')))
    } finally {
      setIsKgWorking(false)
    }
  }

  const handleDownloadCleanDocx = async () => {
    if (isCleanDocxDownloading) return
    setIsCleanDocxDownloading(true)
    try {
      const blob = await documentApi.cleanDocx(displayDoc.id)
      downloadBlob(blob, `${safeFilename(displayDoc.filename, displayDoc.id)}.clean.docx`)
      toast.success('已下载清洗 DOCX')
    } catch (err) {
      console.error('Download clean DOCX failed:', err)
      toast.error(formatApiError(err, '下载清洗 DOCX 失败'))
    } finally {
      setIsCleanDocxDownloading(false)
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

  const [, saveAccessAction, isSavingAccess] = useActionState(async (_state: SaveActionState, formData: FormData): Promise<SaveActionState> => {
    if (!displayDoc?.id) return 'skipped'

    const nextAccessMode = normalizeAccessMode(formData.get('access_mode'))
    const nextAccessGroupIds =
      nextAccessMode === 'partial_members' ? parseStringArrayField(formData.get('access_group_ids_json')) : []
    const nextAccessMembersText = formString(formData.get('access_members_text'))

    try {
      const res = await documentApi.updateAccess(displayDoc.id, {
        mode: nextAccessMode,
        partial_member_list:
          nextAccessMode === 'partial_members' ? parseAccessMembers(nextAccessMembersText) : null,
        partial_group_list: nextAccessMode === 'partial_members' ? nextAccessGroupIds : null,
      })
      queryClient.setQueryData(accessQueryKey, res)
      setAccessMode(res.mode)
      setAccessMembersText((res.partial_member_list || []).join('\n'))
      setAccessGroupIds((res.partial_group_list || []).map(String))
      queryClient.setQueryData<Document | null>(detailQueryKey, (prev) =>
        prev
          ? {
              ...prev,
              access_mode: res.mode === 'inherit' ? null : res.mode,
              owner_id: res.owner_id ?? prev.owner_id,
            }
          : prev
      )
      toast.success(t('toasts.accessUpdated'))
      setAccessDialogOpen(false)
      return 'saved'
    } catch (err) {
      console.error('Update document access failed:', err)
      toast.error(formatApiError(err, t('errors.updateAccessFailed')))
      return 'failed'
    }
  }, 'idle' as SaveActionState)

  const handleVersionsDialogOpenChange = useCallback((next: boolean) => {
    setVersionsDialogOpen(next)
    if (next) {
      versionsQuery.refetch()
    }
  }, [versionsQuery])

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
    versionsQuery.refetch()
  }, [versionsQuery])

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
            label={t('trigger.preview')}
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
                  {t('header.chunkCount', { count: chunks.length })}
                </span>
              </DialogDescription>
            </div>
          </div>

          <div className="flex flex-col items-end gap-2">
            <StatusBadge status={status} />
            <div className="flex flex-wrap justify-end gap-2">
              {parserLabel ? (
                <span className="rounded-full border border-border/60 bg-muted/60 px-2.5 py-1 text-xs font-medium text-muted-foreground">
                  {t('header.parserChip', { label: parserLabel })}
                </span>
              ) : null}
              {chunkStrategyLabel ? (
                <span className="rounded-full border border-border/60 bg-muted/60 px-2.5 py-1 text-xs font-medium text-muted-foreground">
                  {t('header.chunkingChip', { label: chunkStrategyLabel })}
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
          <DocumentDetailSummaryCards
            parserLabel={parserLabel}
            parserBackend={String(pipeline?.parser_backend || parserBackend || '-')}
            requestedParserBackend={requestedParserBackend}
            chunkStrategyLabel={chunkStrategyLabel}
            chunkStrategy={chunkStrategy}
            analyticsRaw={analyticsRaw}
            governanceEnabled={Boolean(displayDoc.governance?.enabled)}
            governanceRulesApplied={displayDoc.governance?.rules_applied}
            governanceChangedDocuments={displayDoc.governance?.changed_documents}
            governanceDroppedDocuments={displayDoc.governance?.dropped_documents}
            governanceRulePacks={governanceRulePacks}
            viewingPipelineHash={viewingPipelineHash}
            activePipelineHash={activePipelineHash}
            lastPipelineHash={lastPipelineHash}
            pipelineEffective={pipelineEffective}
            onCopyPipelineHash={(hash) => detachPromise(copyToClipboard(hash))}
          />

          <DocumentDetailTagsPanel
            editing={tagsEditing}
            saveAction={saveTagsAction}
            saveButton={<DocumentSaveButton disabled={!canSaveTags} />}
            isSaving={isSavingTags}
            tagsDraft={tagsDraft}
            onTagsDraftChange={setTagsDraft}
            optimisticTags={optimisticTags}
            tagsError={tagsError}
            onBeginEdit={beginEditTags}
            onCancelEdit={cancelEditTags}
          />

          <DocumentDetailLifecyclePanel
            editing={lifecycleEditing}
            saveAction={saveLifecycleAction}
            saveButton={<DocumentSaveButton disabled={!canSaveLifecycle} />}
            isSaving={isSavingLifecycle}
            canEdit={!(lifecycleWritable === false || lifecycleWritable == null)}
            editTitle={
              lifecycleWritable === false
                ? t('lifecycle.readOnly')
                : lifecycleWritable == null
                  ? t('lifecycle.permissionChecking')
                  : undefined
            }
            permissionAlertTitle={permissionAlertTitle}
            validationAlertTitle={validationAlertTitle}
            lifecyclePermError={lifecyclePermError}
            lifecycleValidationError={lifecycleValidationError}
            lifecycleError={lifecycleError}
            lifecyclePublicationStatusDraft={lifecyclePublicationStatusDraft}
            onLifecyclePublicationStatusDraftChange={setLifecyclePublicationStatusDraft}
            lifecycleOwnerDraft={lifecycleOwnerDraft}
            onLifecycleOwnerDraftChange={setLifecycleOwnerDraft}
            lifecycleReviewDueDraft={lifecycleReviewDueDraft}
            onLifecycleReviewDueDraftChange={setLifecycleReviewDueDraft}
            lifecycleAuthorityDraft={lifecycleAuthorityDraft}
            onLifecycleAuthorityDraftChange={setLifecycleAuthorityDraft}
            lifecycleSupersedesDraft={lifecycleSupersedesDraft}
            onLifecycleSupersedesDraftChange={setLifecycleSupersedesDraft}
            displayDoc={displayDoc}
            onBeginEdit={beginEditLifecycle}
            onCancelEdit={cancelEditLifecycle}
          />

          <DocumentDetailActivityPanel
            activeView={activeView}
            onActiveViewChange={setActiveView}
            chunksTabId={chunksTabId}
            timelineTabId={timelineTabId}
            chunksPanelId={chunksPanelId}
            timelinePanelId={timelinePanelId}
            scrollParentRef={scrollParentRef}
            onViewTabKeyDown={handleViewTabKeyDown}
            chunkQuery={chunkQuery}
            onChunkQueryChange={setChunkQuery}
            versions={versions}
            viewPipelineHash={viewPipelineHash}
            onViewPipelineHashChange={setViewPipelineHash}
            chunks={chunks}
            chunksTotal={chunksTotal}
            isLoadingDoc={isLoadingDoc}
            detail={detail}
            isLoadingChunks={isLoadingChunks}
            loadError={loadError}
            onRetryChunks={() => {
              detailQuery.refetch()
              accessQuery.refetch()
              lifecyclePermissionQuery.refetch()
              versionsQuery.refetch()
              detachPromise(reloadChunks())
            }}
            onClose={() => setOpen(false)}
            isSearching={isSearching}
            chunkError={chunkError}
            chunkRowVirtualizer={chunkRowVirtualizer}
            canMutateChunks={canMutateChunks}
            chunkOpWorkingId={chunkOpWorkingId}
            onBeginEditChunk={beginEditChunk}
            onToggleChunkDisabled={(chunk) => detachPromise(toggleChunkDisabled(chunk))}
            onReembedChunk={(chunk) => detachPromise(reembedChunk(chunk))}
            onCopyText={(text) => detachPromise(copyToClipboard(text))}
            editingChunkId={editingChunkId}
            editingChunkContent={editingChunkContent}
            onEditingChunkContentChange={setEditingChunkContent}
            onCancelEditChunk={cancelEditChunk}
            onSaveEditChunk={() => detachPromise(saveEditChunk())}
            canLoadMoreChunks={canLoadMoreChunks}
            onLoadMoreChunks={() => detachPromise(loadMoreChunks())}
            timelineItems={timelineItems}
            timelineTotal={timelineTotal}
            isLoadingTimeline={isLoadingTimeline}
            timelineError={timelineError}
            docError={docError}
            onLoadTimeline={() => timelineQuery.refetch()}
            timelineRowVirtualizer={timelineRowVirtualizer}
          />
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
                {t("kg.extract")}
              </Button>
              <Button
                variant="outline"
                onClick={() => detachPromise(handleDownloadCleanDocx())}
                disabled={isCleanDocxDownloading}
                className="w-full gap-2 sm:w-auto"
              >
                {isCleanDocxDownloading ? (
                  <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                ) : (
                  <Download className="h-4 w-4" />
                )}
                下载清洗 DOCX
              </Button>
              <ConfirmDialog
                title={t("kg.deleteDialog.title")}
                description={t('kg.deleteDialog.description')}
                confirmLabel={t('kg.deleteDialog.confirm')}
                cancelLabel={t('kg.deleteDialog.cancel')}
                confirmVariant="destructive"
                confirmDisabled={isKgWorking}
                onConfirm={() => detachPromise(handleDeleteKG())}
              >
                <Button
                  variant="outline"
                  disabled={isKgWorking}
                  className="w-full gap-2 text-destructive hover:bg-destructive/10 hover:text-destructive sm:w-auto"
                >
                  {t('kg.delete')}
                </Button>
              </ConfirmDialog>
            </div>

            <Button variant="secondary" onClick={() => setOpen(false)} className="w-full sm:w-auto">
              {commonT('close')}
            </Button>
          </div>
        </footer>
      </DialogContent>
    </Dialog>
  )
}
