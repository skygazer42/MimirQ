/**
 * 文档详情对话框 - 展示最终切片结果
 */
'use client'

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Calendar, Eye, Hash, Shield } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { DocumentAccessDialog } from '@/components/document-detail-dialog/document-access-dialog'
import {
  DocumentDetailActions,
  type DocumentGraphAction,
} from '@/components/document-detail-dialog/document-detail-actions'
import { DocumentDetailActivityPanel } from '@/components/document-detail-dialog/document-detail-activity-panel'
import { DocumentDetailLifecyclePanel } from '@/components/document-detail-dialog/document-detail-lifecycle-panel'
import { DocumentDetailSummaryCards } from '@/components/document-detail-dialog/document-detail-summary-cards'
import { DocumentDetailTagsPanel } from '@/components/document-detail-dialog/document-detail-tags-panel'
import { DocumentVersionsDialog } from '@/components/document-detail-dialog/document-versions-dialog'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { IconButton } from '@/components/ui/icon-button'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { StatusBadge } from '@/components/ui/status-badge'
import { documentApi } from '@/lib/api/documents'
import { kgApi } from '@/lib/api/graph'
import { formatApiError, toApiErrorInfo } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { buildTagsPatch, getUserTagsFromDocument } from '@/lib/document-user-tags'
import { downloadBlob } from '@/lib/download'
import { getParserLabel } from '@/lib/parser-options'
import { queryKeys } from '@/lib/query-keys'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { formatDate, formatFileSize, detachPromise } from '@/lib/utils'
import type {
  Document,
  DocumentAccessUpdateRequest,
  DocumentTimelineItem,
  DocumentTimelineResponse,
  DocumentVersionList,
} from '@/types/documents'
import type { DocumentChunk, DocumentLifecycleMetadataUpdateRequest } from '@/types/processing'

type DocumentDetailDialogProps = {
  document: Pick<Document, 'id' | 'filename' | 'file_type' | 'file_size' | 'metadata'> &
    Partial<
      Pick<
        Document,
        | 'pipeline'
        | 'governance'
        | 'publication_status'
        | 'lifecycle_owner'
        | 'review_due_at'
        | 'authority_level'
        | 'supersedes_document_id'
      >
    > & { status: string; created_at: string | null }
  trigger?: ReactNode
}

const EMPTY_CHUNKS: DocumentChunk[] = []
const ACTIVE_PIPELINE_VALUE = '__active__'
const CHUNK_PAGE_SIZE = 200
type MetadataSaveKind = 'tags' | 'lifecycle' | 'access' | 'version'
type ChunkEditor = { chunkId: string; content: string }

function sameTags(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((tag, index) => tag === right[index])
}

export function DocumentDetailDialog({ document: initialDocument, trigger }: Readonly<DocumentDetailDialogProps>) {
  const commonT = useTranslations('Common')
  const t = useTranslations('DocumentDetailDialog')
  const viewTabsId = useId()
  const chunksTabId = `${viewTabsId}-chunks-tab`
  const timelineTabId = `${viewTabsId}-timeline-tab`
  const chunksPanelId = `${viewTabsId}-chunks-panel`
  const timelinePanelId = `${viewTabsId}-timeline-panel`
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const metadataSessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const [activeView, setActiveView] = useState<'chunks' | 'timeline'>('chunks')

  const scrollParentRef = useRef<HTMLDivElement>(null)

  const [chunks, setChunks] = useState<DocumentChunk[]>(EMPTY_CHUNKS)
  const [chunksTotal, setChunksTotal] = useState(0)
  const [isLoadingChunks, setIsLoadingChunks] = useState(false)
  const [chunkError, setChunkError] = useState<string | null>(null)
  const [versionsDialogOpen, setVersionsDialogOpen] = useState(false)
  const [viewPipelineHash, setViewPipelineHash] = useState<string>(ACTIVE_PIPELINE_VALUE)

  const [chunkQuery, setChunkQuery] = useState('')
  const chunkScope = useMemo(
    () => ({
      documentId: initialDocument.id,
      open,
      activeView,
      query: chunkQuery,
      pipelineHash: viewPipelineHash,
      sessionKey: metadataSessionKey,
    }),
    [activeView, chunkQuery, initialDocument.id, open, viewPipelineHash, metadataSessionKey],
  )
  const chunkScopeRef = useRef<typeof chunkScope | null>(null)
  const chunkRequestRef = useRef<AbortController | null>(null)

  useLayoutEffect(() => {
    chunkScopeRef.current = chunkScope
    setChunks(EMPTY_CHUNKS)
    setChunksTotal(0)
    setChunkError(null)
    setIsLoadingChunks(chunkScope.open && chunkScope.activeView === 'chunks')
    return () => {
      chunkScopeRef.current = null
      const request = chunkRequestRef.current
      chunkRequestRef.current = null
      request?.abort()
    }
  }, [chunkScope])

  const [chunkEditor, setChunkEditor] = useState<ChunkEditor | null>(null)
  const [accessDialogOpen, setAccessDialogOpen] = useState(false)

  const detailQueryKey = queryKeys.documents.detail(initialDocument.id)
  const accessQueryKey = queryKeys.documents.access(initialDocument.id)
  const versionsQueryKey = queryKeys.documents.versions(initialDocument.id)
  const timelineQueryParams = { limit: 200 } as const
  const timelineQueryKey = queryKeys.documents.timeline(initialDocument.id, timelineQueryParams)

  const detailQuery = useQuery({
    queryKey: detailQueryKey,
    queryFn: ({ signal }) => documentApi.get(initialDocument.id, undefined, { signal }),
    enabled: open,
  })

  const accessQuery = useQuery({
    queryKey: accessQueryKey,
    queryFn: ({ signal }) => documentApi.getAccess(initialDocument.id, { signal }),
    enabled: open,
    retry: false,
  })

  const lifecycleQueryKey = queryKeys.documents.lifecycleMetadata(initialDocument.id)
  const lifecycleQuery = useQuery({
    queryKey: lifecycleQueryKey,
    queryFn: ({ signal }) => documentApi.getLifecycleMetadata(initialDocument.id, { signal }),
    enabled: open,
    retry: false,
  })
  let lifecycleLoadError: string | null = null
  if (lifecycleQuery.error !== null) {
    const info = toApiErrorInfo(lifecycleQuery.error, t('errors.lifecyclePermissionCheckUnknown'))
    lifecycleLoadError =
      info.status === 403
        ? t('lifecycle.readOnly')
        : formatApiError(lifecycleQuery.error, t('errors.lifecyclePermissionCheckUnknown'))
  }

  const versionsQuery = useQuery<DocumentVersionList>({
    queryKey: versionsQueryKey,
    queryFn: ({ signal }) => documentApi.listVersions(initialDocument.id, { signal }),
    enabled: open,
  })

  const timelineQuery = useQuery<DocumentTimelineResponse>({
    queryKey: timelineQueryKey,
    queryFn: ({ signal }) => documentApi.getTimeline(initialDocument.id, timelineQueryParams, { signal }),
    enabled: open && activeView === 'timeline',
  })

  const detail = detailQuery.data ?? null
  const accessInfo = accessQuery.data
  const accessLoadError =
    accessQuery.error === null ? null : formatApiError(accessQuery.error, t('errors.loadAccessFailed'))
  const versions = versionsQuery.data ?? null
  const timeline = timelineQuery.data ?? null
  const docError = detailQuery.error ? formatApiError(detailQuery.error, t('errors.loadDetailFailed')) : null
  const versionsError = versionsQuery.error ? formatApiError(versionsQuery.error, t('errors.loadVersionsFailed')) : null
  const timelineError = timelineQuery.error ? formatApiError(timelineQuery.error, t('errors.loadTimelineFailed')) : null

  const persistedTags = useMemo(
    () => getUserTagsFromDocument(detail === null ? initialDocument : detail),
    [detail, initialDocument],
  )
  const [tagsEditing, setTagsEditing] = useState(false)
  const [tagsDraft, setTagsDraft] = useState<string[]>([])
  const [tagsError, setTagsError] = useState<string | null>(null)
  const metadataView = useMemo(
    () => ({ documentId: initialDocument.id, open, sessionKey: metadataSessionKey }),
    [initialDocument.id, open, metadataSessionKey],
  )
  const metadataViewRef = useRef<typeof metadataView | null>(null)
  const metadataSaves = useRef(new Map<string, MetadataSaveKind>())
  const [pendingMetadata, setPendingMetadata] = useState<ReadonlyMap<string, MetadataSaveKind>>(() => new Map())
  const metadataResourceKey = JSON.stringify([initialDocument.id, metadataSessionKey])
  const activeMetadataSave = pendingMetadata.get(metadataResourceKey)
  const isSavingTags = activeMetadataSave === 'tags'
  const isSavingLifecycle = activeMetadataSave === 'lifecycle'
  const isSavingAccess = activeMetadataSave === 'access'
  const isVersionWorking = activeMetadataSave === 'version'
  const metadataBusy = activeMetadataSave !== undefined
  const graphRequests = useRef(new Map<string, DocumentGraphAction>())
  const [pendingGraphRequests, setPendingGraphRequests] = useState<ReadonlyMap<string, DocumentGraphAction>>(
    () => new Map(),
  )
  const downloadRequests = useRef(new Set<string>())
  const [pendingDownloads, setPendingDownloads] = useState<ReadonlySet<string>>(() => new Set())

  type ChunkSave = {
    key: string
    resourceKey: string
    chunkId: string
    view: typeof metadataView
    scope: typeof chunkScope
  }
  const chunkSaves = useRef(new Map<string, ChunkSave>())
  const [pendingChunkSaves, setPendingChunkSaves] = useState<ReadonlyMap<string, ChunkSave>>(() => new Map())
  const pendingChunkIds = new Set(
    Array.from(pendingChunkSaves.values())
      .filter((operation) => operation.resourceKey === metadataResourceKey)
      .map((operation) => operation.chunkId),
  )

  useLayoutEffect(() => {
    metadataViewRef.current = metadataView
    setTagsEditing(false)
    setTagsDraft([])
    setTagsError(null)
    setAccessDialogOpen(false)
    setVersionsDialogOpen(false)
    setChunkEditor(null)
    return () => {
      if (metadataViewRef.current === metadataView) metadataViewRef.current = null
    }
  }, [metadataView])

  const canMutateChunks = viewPipelineHash === ACTIVE_PIPELINE_VALUE && !isVersionWorking

  function beginMetadataSave(kind: MetadataSaveKind): boolean {
    if (metadataSaves.current.has(metadataResourceKey)) return false
    metadataSaves.current.set(metadataResourceKey, kind)
    setPendingMetadata((operations) => new Map(operations).set(metadataResourceKey, kind))
    return true
  }

  function finishMetadataSave(resourceKey: string) {
    metadataSaves.current.delete(resourceKey)
    if (metadataViewRef.current === null) return
    setPendingMetadata((operations) => {
      const pending = new Map(operations)
      pending.delete(resourceKey)
      return pending
    })
  }

  const focusViewTab = useCallback(
    (nextView: 'chunks' | 'timeline') => {
      setActiveView(nextView)
      globalThis.window.requestAnimationFrame(() => {
        globalThis.document.getElementById(nextView === 'chunks' ? chunksTabId : timelineTabId)?.focus()
      })
    },
    [chunksTabId, timelineTabId],
  )

  const handleViewTabKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLButtonElement>) => {
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
    },
    [focusViewTab],
  )

  function beginEditChunk(chunk: DocumentChunk) {
    if (chunkEditor !== null || !canMutateChunks || pendingChunkIds.has(chunk.id)) return
    setChunkEditor({ chunkId: chunk.id, content: chunk.content })
  }

  function cancelEditChunk() {
    if (chunkEditor !== null && pendingChunkIds.has(chunkEditor.chunkId)) return
    setChunkEditor(null)
  }

  function changeChunkContent(content: string) {
    setChunkEditor((current) => (current === null ? null : { ...current, content }))
  }

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

  function changeTagsDraft(next: string[]) {
    if (sameTags(tagsDraft, next)) return
    setTagsDraft(next)
    setTagsError(null)
  }

  const hasPendingTagChanges = tagsEditing && !sameTags(tagsDraft, persistedTags)

  async function saveTags(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (
      !metadataView.open ||
      metadataViewRef.current !== metadataView ||
      getAuthSessionKey() !== metadataView.sessionKey
    )
      return
    if (!hasPendingTagChanges) return

    const view = metadataView
    const tags = [...tagsDraft]
    const query = queryClient.getQueryCache().find({ queryKey: detailQueryKey, exact: true })
    if (query === undefined) {
      setTagsError(t('errors.tagsRefreshRequired'))
      return
    }

    if (!beginMetadataSave('tags')) return
    setTagsError(null)
    try {
      const updated = await documentApi.patchUserMetadata(view.documentId, buildTagsPatch(tags))
      if (getAuthSessionKey() !== view.sessionKey) return

      if (queryClient.getQueryCache().find({ queryKey: detailQueryKey, exact: true }) === query) {
        await queryClient.cancelQueries({ queryKey: detailQueryKey, exact: true })
      }
      if (getAuthSessionKey() !== view.sessionKey) return
      if (queryClient.getQueryCache().find({ queryKey: detailQueryKey, exact: true }) !== query) {
        if (metadataViewRef.current === view) setTagsError(t('errors.tagsRefreshRequired'))
        return
      }
      queryClient.setQueryData(detailQueryKey, updated)
      if (metadataViewRef.current !== view) return

      setTagsEditing(false)
      setTagsDraft([])
      toast.success(t('toasts.tagsUpdated'))
    } catch (error) {
      reportClientError('Update document tags failed', error)
      if (metadataViewRef.current === view && getAuthSessionKey() === view.sessionKey) {
        setTagsError(formatApiError(error, t('errors.saveTagsFailed')))
      }
    } finally {
      finishMetadataSave(metadataResourceKey)
    }
  }

  const canSaveTags = hasPendingTagChanges && !metadataBusy

  function beginChunkSave(chunkId: string): ChunkSave | null {
    if (
      !canMutateChunks ||
      !metadataView.open ||
      metadataViewRef.current !== metadataView ||
      chunkScopeRef.current !== chunkScope ||
      getAuthSessionKey() !== metadataView.sessionKey ||
      metadataSaves.current.get(metadataResourceKey) === 'version'
    )
      return null
    const key = JSON.stringify([metadataResourceKey, chunkId])
    if (chunkSaves.current.has(key)) return null
    const operation = { key, resourceKey: metadataResourceKey, chunkId, view: metadataView, scope: chunkScope }
    chunkSaves.current.set(key, operation)
    setPendingChunkSaves((operations) => new Map(operations).set(key, operation))
    return operation
  }

  function isCurrentChunkSave(operation: ChunkSave): boolean {
    return (
      metadataViewRef.current === operation.view &&
      chunkScopeRef.current === operation.scope &&
      getAuthSessionKey() === operation.view.sessionKey
    )
  }

  function isCurrentDocument(view: typeof metadataView): boolean {
    const current = metadataViewRef.current
    return (
      current !== null &&
      current.documentId === view.documentId &&
      current.sessionKey === view.sessionKey &&
      getAuthSessionKey() === view.sessionKey
    )
  }

  function isViewingDocument(view: typeof metadataView): boolean {
    return metadataViewRef.current?.open === true && isCurrentDocument(view)
  }

  function finishChunkSave(operation: ChunkSave) {
    chunkSaves.current.delete(operation.key)
    if (metadataViewRef.current === null) return
    setPendingChunkSaves((operations) => {
      const pending = new Map(operations)
      pending.delete(operation.key)
      return pending
    })
  }

  async function saveEditChunk() {
    if (chunkEditor === null) return
    const editor = chunkEditor
    const operation = beginChunkSave(editor.chunkId)
    if (operation === null) return
    try {
      const updated = await documentApi.updateChunk(operation.view.documentId, editor.chunkId, {
        content: editor.content,
      })
      if (isViewingDocument(operation.view)) {
        if (isCurrentChunkSave(operation) && operation.scope.query.trim().length === 0) {
          setChunks((current) => current.map((chunk) => (chunk.id === editor.chunkId ? updated : chunk)))
        } else {
          await reloadChunks()
        }
      }
      if (metadataViewRef.current !== operation.view || getAuthSessionKey() !== operation.view.sessionKey) return
      setChunkEditor((current) => (current === editor ? null : current))
      toast.success(t('toasts.chunkSaved'))
    } catch (err) {
      reportClientError('Update chunk failed', err)
      if (isCurrentChunkSave(operation)) toast.error(formatApiError(err, t('errors.saveChunkFailed')))
    } finally {
      finishChunkSave(operation)
    }
  }

  async function toggleChunkDisabled(chunk: DocumentChunk) {
    const operation = beginChunkSave(chunk.id)
    if (operation === null) return
    try {
      const updated = chunk.disabled_at
        ? await documentApi.enableChunk(operation.view.documentId, chunk.id)
        : await documentApi.disableChunk(operation.view.documentId, chunk.id)
      if (!isCurrentChunkSave(operation)) {
        if (isViewingDocument(operation.view)) await reloadChunks()
        return
      }
      setChunks((current) => current.map((item) => (item.id === chunk.id ? updated : item)))
      toast.success(chunk.disabled_at ? t('toasts.chunkEnabled') : t('toasts.chunkDisabled'))
    } catch (err) {
      reportClientError('Toggle chunk disabled failed', err)
      if (isCurrentChunkSave(operation)) toast.error(formatApiError(err, t('errors.chunkOperationFailed')))
    } finally {
      finishChunkSave(operation)
    }
  }

  async function reembedChunk(chunk: DocumentChunk) {
    const operation = beginChunkSave(chunk.id)
    if (operation === null) return
    try {
      const res = await documentApi.reembedChunks(operation.view.documentId, {
        chunk_ids: [chunk.id],
        include_disabled: Boolean(chunk.disabled_at),
      })
      if (res.denied?.includes(chunk.id)) throw new Error(t('errors.reembedDenied'))
      if (res.not_found?.includes(chunk.id)) throw new Error(t('errors.reembedNotFound'))
      if (res.conflicts?.includes(chunk.id) || res.reembedded !== 1) throw new Error(t('errors.reembedConflict'))
      if (isCurrentChunkSave(operation)) toast.success(t('toasts.chunkReembedded', { count: res.reembedded }))
    } catch (err) {
      reportClientError('Re-embed chunk failed', err)
      if (isCurrentChunkSave(operation)) toast.error(formatApiError(err, t('errors.reembedFailed')))
    } finally {
      finishChunkSave(operation)
    }
  }
  async function saveLifecycle(patch: DocumentLifecycleMetadataUpdateRequest): Promise<'saved' | 'skipped'> {
    if (
      !metadataView.open ||
      metadataViewRef.current !== metadataView ||
      getAuthSessionKey() !== metadataView.sessionKey
    )
      return 'skipped'
    if (!lifecycleQuery.isSuccess || lifecycleQuery.isFetching) return 'skipped'
    const view = metadataView
    const cache = queryClient.getQueryCache()
    const lifecycleQueryEntity = cache.find({ queryKey: lifecycleQueryKey, exact: true })
    const detailQueryEntity = cache.find({ queryKey: detailQueryKey, exact: true })
    if (lifecycleQueryEntity === undefined) throw new Error(t('errors.lifecycleRefreshRequired'))
    if (!beginMetadataSave('lifecycle')) return 'skipped'
    try {
      const updated = await documentApi.patchLifecycleMetadata(view.documentId, patch)
      if (getAuthSessionKey() !== view.sessionKey) return 'skipped'
      if (cache.find({ queryKey: lifecycleQueryKey, exact: true }) === lifecycleQueryEntity) {
        await queryClient.cancelQueries({ queryKey: lifecycleQueryKey, exact: true })
      }
      if (getAuthSessionKey() !== view.sessionKey) return 'skipped'
      if (
        detailQueryEntity !== undefined &&
        cache.find({ queryKey: detailQueryKey, exact: true }) === detailQueryEntity
      ) {
        await queryClient.cancelQueries({ queryKey: detailQueryKey, exact: true })
      }
      if (getAuthSessionKey() !== view.sessionKey) return 'skipped'
      if (cache.find({ queryKey: lifecycleQueryKey, exact: true }) !== lifecycleQueryEntity) {
        if (metadataViewRef.current === view) throw new Error(t('errors.lifecycleRefreshRequired'))
        return 'skipped'
      }
      queryClient.setQueryData(lifecycleQueryKey, updated)
      if (
        detailQueryEntity !== undefined &&
        cache.find({ queryKey: detailQueryKey, exact: true }) === detailQueryEntity
      ) {
        queryClient.setQueryData<Document>(detailQueryKey, (current) =>
          current === undefined ? undefined : { ...current, ...updated },
        )
        await queryClient.invalidateQueries({ queryKey: detailQueryKey, exact: true })
      }
      if (metadataViewRef.current !== view || getAuthSessionKey() !== view.sessionKey) return 'skipped'
      if (cache.find({ queryKey: lifecycleQueryKey, exact: true }) !== lifecycleQueryEntity) {
        throw new Error(t('errors.lifecycleRefreshRequired'))
      }
      toast.success(t('toasts.lifecycleUpdated'))
      return 'saved'
    } catch (error) {
      reportClientError('Update document lifecycle metadata failed', error)
      if (metadataViewRef.current !== view || getAuthSessionKey() !== view.sessionKey) return 'skipped'
      throw error
    } finally {
      finishMetadataSave(metadataResourceKey)
    }
  }

  const loadChunksPage = useCallback(
    async (scope: typeof chunkScope, skip: number) => {
      if (chunkScopeRef.current !== scope || !scope.open || scope.activeView !== 'chunks') return
      if (getAuthSessionKey() !== scope.sessionKey) return

      const previousRequest = chunkRequestRef.current
      const request = new AbortController()
      chunkRequestRef.current = request
      previousRequest?.abort()
      const isCurrent = () => chunkRequestRef.current === request && getAuthSessionKey() === scope.sessionKey
      const firstPage = skip === 0
      setIsLoadingChunks(true)
      setChunkError(null)
      if (firstPage) {
        setChunks(EMPTY_CHUNKS)
        setChunksTotal(0)
      }

      try {
        const q = scope.query.trim()
        const pipelineHash = scope.pipelineHash === ACTIVE_PIPELINE_VALUE ? undefined : scope.pipelineHash
        const page = await documentApi.listChunks(
          scope.documentId,
          { skip, limit: CHUNK_PAGE_SIZE, q: q.length === 0 ? undefined : q, pipeline_hash: pipelineHash },
          { signal: request.signal },
        )
        if (!isCurrent()) return
        setChunks((current) => (firstPage ? page.items : [...current, ...page.items]))
        setChunksTotal(page.total)
      } catch (error) {
        if (!isCurrent()) return
        reportClientError(firstPage ? 'Load document chunks error' : 'Load more chunks error', error)
        setChunkError(formatApiError(error, t(firstPage ? 'errors.loadChunksFailed' : 'errors.loadMoreChunksFailed')))
      } finally {
        if (chunkRequestRef.current === request) {
          chunkRequestRef.current = null
          setIsLoadingChunks(false)
        }
      }
    },
    [t],
  )

  const reloadChunks = useCallback(async () => {
    const scope = chunkScopeRef.current
    if (scope !== null) await loadChunksPage(scope, 0)
  }, [loadChunksPage])

  async function loadMoreChunks() {
    if (chunkRequestRef.current !== null || chunks.length >= chunksTotal) return
    await loadChunksPage(chunkScope, chunks.length)
  }

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen) setActiveView('chunks')
    setOpen(nextOpen)
  }

  useEffect(() => {
    if (!chunkScope.open || chunkScope.activeView !== 'chunks') return
    const handle = globalThis.window.setTimeout(
      () => {
        detachPromise(reloadChunks())
      },
      chunkScope.query.trim().length > 0 ? 250 : 0,
    )
    return () => globalThis.window.clearTimeout(handle)
  }, [chunkScope, reloadChunks])
  const displayDoc = detail === null ? initialDocument : detail
  const displayedChunkCount =
    viewPipelineHash === ACTIVE_PIPELINE_VALUE
      ? detail?.chunk_count
      : versions?.items?.find((version) => version.pipeline_hash === viewPipelineHash)?.chunk_count
  const pipeline = displayDoc.pipeline
  const parserBackend = pipeline?.parser_backend
  const chunkStrategy = pipeline?.chunk_strategy
  const parserLabel = parserBackend ? getParserLabel(parserBackend) : null
  const chunkStrategyLabel = chunkStrategy ? getChunkStrategyLabel(chunkStrategy) : null

  const activePipelineHash = versions === null ? pipeline?.active_pipeline_hash : versions.active_pipeline_hash
  const viewingPipelineHash = viewPipelineHash === ACTIVE_PIPELINE_VALUE ? activePipelineHash : viewPipelineHash

  let accessModeLabel = t('accessModes.loading')
  if (accessQuery.isError) accessModeLabel = t('accessModes.unavailable')
  else if (accessInfo !== undefined) {
    switch (accessInfo.mode) {
      case 'inherit':
        accessModeLabel = t('accessModes.inherit')
        break
      case 'only_me':
        accessModeLabel = t('accessModes.onlyMe')
        break
      case 'partial_members':
        accessModeLabel = t('accessModes.partialMembers')
        break
      case 'all_team_members':
        accessModeLabel = t('accessModes.allTeamMembers')
        break
    }
  }

  const isSearching = chunkQuery.trim().length > 0
  const canLoadMoreChunks = chunks.length < chunksTotal
  const loadError = docError === null ? chunkError : docError
  const timelineItems: DocumentTimelineItem[] = timeline === null || timeline.items === undefined ? [] : timeline.items
  const timelineTotal = timeline === null ? 0 : timeline.total
  // eslint-disable-next-line react-hooks/incompatible-library
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

  const copyToClipboard = useCallback(
    async (content: string) => {
      try {
        if (!navigator.clipboard?.writeText) {
          throw new Error('Clipboard API unavailable')
        }
        await navigator.clipboard.writeText(content)
        toast.success(t('toasts.copySuccess'))
      } catch (err) {
        reportClientError('Copy failed', err)
        toast.error(t('errors.copyFailed'))
      }
    },
    [t],
  )

  async function changeVersion(action: 'activate' | 'delete', pipelineHash: string): Promise<void> {
    if (
      !metadataView.open ||
      metadataViewRef.current !== metadataView ||
      getAuthSessionKey() !== metadataView.sessionKey
    )
      return
    if (!versionsQuery.isSuccess || versionsQuery.isFetching) return
    if (Array.from(chunkSaves.current.values()).some((operation) => operation.resourceKey === metadataResourceKey))
      return

    const view = metadataView
    const cache = queryClient.getQueryCache()
    const sourceQueries = [detailQueryKey, accessQueryKey, lifecycleQueryKey, versionsQueryKey].map((queryKey) => ({
      queryKey,
      entity: cache.find({ queryKey, exact: true }),
    }))
    const versionQueryEntity = cache.find({ queryKey: versionsQueryKey, exact: true })
    if (versionQueryEntity === undefined) throw new Error(t('errors.versionsRefreshRequired'))
    if (!beginMetadataSave('version')) return

    let versionUpdated = false
    try {
      if (action === 'activate') await documentApi.activateVersion(view.documentId, pipelineHash)
      else await documentApi.deleteVersion(view.documentId, pipelineHash)
      versionUpdated = true
      if (getAuthSessionKey() !== view.sessionKey) return
      if (metadataViewRef.current === view) {
        if (action === 'activate' || viewPipelineHash === pipelineHash) setViewPipelineHash(ACTIVE_PIPELINE_VALUE)
        toast.success(t(action === 'activate' ? 'toasts.versionActivated' : 'toasts.versionDeleted'))
      }

      await Promise.all(
        sourceQueries.map(async ({ queryKey, entity }) => {
          if (entity === undefined || cache.find({ queryKey, exact: true }) !== entity) return
          await queryClient.cancelQueries({ queryKey, exact: true })
          if (getAuthSessionKey() !== view.sessionKey || cache.find({ queryKey, exact: true }) !== entity) return
          await queryClient.invalidateQueries({ queryKey, exact: true }, { throwOnError: true })
        }),
      )
      if (metadataViewRef.current !== view || getAuthSessionKey() !== view.sessionKey) return
      if (cache.find({ queryKey: versionsQueryKey, exact: true }) !== versionQueryEntity) {
        throw new Error(t('errors.versionsRefreshRequired'))
      }
      await reloadChunks()
    } catch (error) {
      reportClientError('Update document version failed', error)
      if (metadataViewRef.current !== view || getAuthSessionKey() !== view.sessionKey) return
      if (versionUpdated) {
        toast.warning(`版本已更新，读取失败。 ${formatApiError(error, t('errors.versionsRefreshRequired'))}`)
        return
      }
      throw error
    } finally {
      finishMetadataSave(metadataResourceKey)
    }
  }

  async function changeDocumentGraph(action: DocumentGraphAction): Promise<void> {
    if (
      !metadataView.open ||
      metadataViewRef.current !== metadataView ||
      getAuthSessionKey() !== metadataView.sessionKey
    )
      return
    if (graphRequests.current.has(metadataResourceKey)) return
    if (action === 'extract' && displayDoc.status !== 'completed') return
    const view = metadataView
    graphRequests.current.set(metadataResourceKey, action)
    setPendingGraphRequests((requests) => new Map(requests).set(metadataResourceKey, action))
    try {
      if (action === 'extract') {
        await kgApi.extract(view.documentId, { async: true, replace_existing: true, prune_orphan_entities: true })
        if (isCurrentDocument(view)) toast.success(t('toasts.kgExtractStarted'))
      } else {
        const result = await kgApi.deleteDocumentKG(view.documentId, { prune_orphan_entities: true })
        if (isCurrentDocument(view))
          toast.success(t('toasts.kgDeleted', { events: result.events_deleted, entities: result.entities_pruned }))
      }
    } catch (error) {
      reportClientError('Change document graph failed', error)
      if (!isCurrentDocument(view)) return
      if (action === 'delete' && metadataViewRef.current === view) throw error
      toast.error(formatApiError(error, t(action === 'extract' ? 'errors.kgExtractFailed' : 'errors.kgDeleteFailed')))
    } finally {
      graphRequests.current.delete(metadataResourceKey)
      if (metadataViewRef.current !== null)
        setPendingGraphRequests((requests) => {
          const pending = new Map(requests)
          pending.delete(metadataResourceKey)
          return pending
        })
    }
  }

  async function downloadCleanDocx(): Promise<void> {
    if (
      !metadataView.open ||
      metadataViewRef.current !== metadataView ||
      getAuthSessionKey() !== metadataView.sessionKey
    )
      return
    if (downloadRequests.current.has(metadataResourceKey)) return
    const view = metadataView
    const filename = `${displayDoc.filename}.clean.docx`
    downloadRequests.current.add(metadataResourceKey)
    setPendingDownloads((requests) => new Set(requests).add(metadataResourceKey))
    try {
      const blob = await documentApi.cleanDocx(view.documentId)
      if (!isCurrentDocument(view)) return
      downloadBlob(filename, blob)
      toast.success(t('toasts.cleanDocxDownloadStarted'))
    } catch (error) {
      reportClientError('Download clean DOCX failed', error)
      if (isCurrentDocument(view)) toast.error(formatApiError(error, t('errors.downloadCleanDocxFailed')))
    } finally {
      downloadRequests.current.delete(metadataResourceKey)
      if (metadataViewRef.current !== null)
        setPendingDownloads((requests) => {
          const pending = new Set(requests)
          pending.delete(metadataResourceKey)
          return pending
        })
    }
  }

  async function saveAccess(payload: DocumentAccessUpdateRequest): Promise<'saved' | 'skipped'> {
    if (
      !metadataView.open ||
      !accessDialogOpen ||
      metadataViewRef.current !== metadataView ||
      getAuthSessionKey() !== metadataView.sessionKey
    )
      return 'skipped'
    if (!accessQuery.isSuccess || accessQuery.isFetching) return 'skipped'

    const view = metadataView
    const cache = queryClient.getQueryCache()
    const accessQueryEntity = cache.find({ queryKey: accessQueryKey, exact: true })
    const detailQueryEntity = cache.find({ queryKey: detailQueryKey, exact: true })
    if (accessQueryEntity === undefined) throw new Error(t('errors.accessRefreshRequired'))

    if (!beginMetadataSave('access')) return 'skipped'
    try {
      const updated = await documentApi.updateAccess(view.documentId, payload)
      if (getAuthSessionKey() !== view.sessionKey) return 'skipped'
      if (cache.find({ queryKey: accessQueryKey, exact: true }) === accessQueryEntity) {
        await queryClient.cancelQueries({ queryKey: accessQueryKey, exact: true })
      }
      if (getAuthSessionKey() !== view.sessionKey) return 'skipped'
      if (
        detailQueryEntity !== undefined &&
        cache.find({ queryKey: detailQueryKey, exact: true }) === detailQueryEntity
      ) {
        await queryClient.cancelQueries({ queryKey: detailQueryKey, exact: true })
      }
      if (getAuthSessionKey() !== view.sessionKey) return 'skipped'
      if (cache.find({ queryKey: accessQueryKey, exact: true }) !== accessQueryEntity) {
        if (metadataViewRef.current === view) throw new Error(t('errors.accessRefreshRequired'))
        return 'skipped'
      }

      queryClient.setQueryData(accessQueryKey, updated)
      if (
        detailQueryEntity !== undefined &&
        cache.find({ queryKey: detailQueryKey, exact: true }) === detailQueryEntity
      ) {
        queryClient.setQueryData<Document>(detailQueryKey, (current) =>
          current === undefined
            ? undefined
            : {
                ...current,
                access_mode: updated.mode === 'inherit' ? null : updated.mode,
                owner_id: updated.owner_id,
              },
        )
      }
      if (metadataViewRef.current !== view || getAuthSessionKey() !== view.sessionKey) return 'skipped'
      toast.success(t('toasts.accessUpdated'))
      setAccessDialogOpen(false)
      return 'saved'
    } catch (error) {
      reportClientError('Update document access failed', error)
      if (metadataViewRef.current !== view || getAuthSessionKey() !== view.sessionKey) return 'skipped'
      throw error
    } finally {
      finishMetadataSave(metadataResourceKey)
    }
  }

  const handleVersionsDialogOpenChange = useCallback(
    (next: boolean) => {
      if (!next && isVersionWorking) return
      setVersionsDialogOpen(next)
      if (next) {
        versionsQuery.refetch()
      }
    },
    [isVersionWorking, versionsQuery],
  )

  const handleAccessDialogOpenChange = useCallback(
    (next: boolean) => {
      if (!next && isSavingAccess) return
      setAccessDialogOpen(next)
    },
    [isSavingAccess],
  )

  const handleVersionsRefresh = useCallback(() => {
    versionsQuery.refetch()
  }, [versionsQuery])

  const handleCopyText = useCallback(
    (text: string) => {
      detachPromise(copyToClipboard(text))
    },
    [copyToClipboard],
  )

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        {trigger === undefined ? (
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
        ) : (
          trigger
        )}
      </DialogTrigger>

      <DialogContent className="!max-w-5xl w-[calc(100%-2rem)] h-[80dvh] max-h-[calc(100dvh-2rem)] grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-lg border border-foreground/10 bg-background !p-0 !gap-0">
        {/* Header */}
        <header className="flex flex-col gap-3 border-b border-foreground/15 bg-background px-6 py-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
          <div className="flex items-start gap-4 min-w-0">
            <div className="grid h-12 w-12 shrink-0 place-items-center rounded-xl border border-foreground/10 bg-background/70 text-primary">
              <FileTypeIcon type={displayDoc.file_type} filename={displayDoc.filename} className="size-6" />
            </div>
            <div className="min-w-0">
              <DialogTitle className="truncate">{displayDoc.filename}</DialogTitle>
              <DialogDescription className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                <span className="inline-flex items-center gap-1">
                  <FileTypeIcon type={displayDoc.file_type} filename={displayDoc.filename} className="size-3.5" />
                  {displayDoc.file_type}
                </span>
                <span className="text-muted-foreground/40">|</span>
                <span>{formatFileSize(displayDoc.file_size)}</span>
                <span className="text-muted-foreground/40">|</span>
                <span className="inline-flex items-center gap-1">
                  <Calendar className="h-3.5 w-3.5" />
                  {displayDoc.created_at === null ? t('cards.notProvided') : formatDate(displayDoc.created_at)}
                </span>
                <span className="text-muted-foreground/40">|</span>
                <span className="inline-flex items-center gap-1">
                  <Hash className="h-3.5 w-3.5" />
                  {displayedChunkCount === undefined
                    ? t('cards.notProvided')
                    : t('header.chunkCount', { count: displayedChunkCount })}
                </span>
              </DialogDescription>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 sm:flex-col sm:items-end">
            {detail === null ? (
              <Badge variant="outline">{initialDocument.status}</Badge>
            ) : (
              <StatusBadge status={detail.status} />
            )}
            <div className="flex flex-wrap justify-end gap-2">
              {parserLabel ? (
                <span className="rounded-full border border-foreground/10 bg-background/70 px-2.5 py-1 text-xs font-medium text-muted-foreground">
                  {t('header.parserChip', { label: parserLabel })}
                </span>
              ) : null}
              {chunkStrategyLabel ? (
                <span className="rounded-full border border-foreground/10 bg-background/70 px-2.5 py-1 text-xs font-medium text-muted-foreground">
                  {t('header.chunkingChip', { label: chunkStrategyLabel })}
                </span>
              ) : null}
              <span className="inline-flex items-center gap-1 rounded-full border border-foreground/10 bg-background/70 px-2.5 py-1 text-xs font-medium text-muted-foreground">
                <Shield className="h-3.5 w-3.5" />
                {accessModeLabel}
              </span>
            </div>
          </div>
        </header>

        {/* Body */}
        <main className="min-h-0 min-w-0 overflow-y-auto p-4 sm:p-6 flex flex-col gap-4">
          <DocumentDetailSummaryCards
            document={displayDoc}
            viewingPipelineHash={viewingPipelineHash}
            activePipelineHash={activePipelineHash}
            onCopyPipelineHash={(hash) => detachPromise(copyToClipboard(hash))}
          />

          <DocumentDetailTagsPanel
            editing={tagsEditing}
            onSave={saveTags}
            canSave={canSaveTags}
            isSaving={isSavingTags}
            tagsDraft={tagsDraft}
            onTagsDraftChange={changeTagsDraft}
            tags={persistedTags}
            tagsError={tagsError}
            onBeginEdit={beginEditTags}
            onCancelEdit={cancelEditTags}
          />

          <DocumentDetailLifecyclePanel
            key={JSON.stringify([initialDocument.id, metadataSessionKey, open])}
            document={displayDoc}
            metadata={lifecycleQuery.data}
            canEdit={lifecycleQuery.isSuccess}
            loading={lifecycleQuery.isFetching}
            loadError={lifecycleLoadError}
            isSaving={isSavingLifecycle}
            metadataBusy={metadataBusy}
            onRetry={() => {
              void lifecycleQuery.refetch()
            }}
            onSave={saveLifecycle}
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
            isLoadingDoc={detailQuery.isLoading}
            detail={detail}
            isLoadingChunks={isLoadingChunks}
            loadError={loadError}
            onRetryChunks={() => {
              detailQuery.refetch()
              accessQuery.refetch()
              lifecycleQuery.refetch()
              versionsQuery.refetch()
              detachPromise(reloadChunks())
            }}
            onClose={() => setOpen(false)}
            isSearching={isSearching}
            chunkError={chunkError}
            chunkRowVirtualizer={chunkRowVirtualizer}
            canMutateChunks={canMutateChunks}
            pendingChunkIds={pendingChunkIds}
            onBeginEditChunk={beginEditChunk}
            onToggleChunkDisabled={(chunk) => detachPromise(toggleChunkDisabled(chunk))}
            onReembedChunk={(chunk) => detachPromise(reembedChunk(chunk))}
            onCopyText={(text) => detachPromise(copyToClipboard(text))}
            editingChunkId={chunkEditor === null ? null : chunkEditor.chunkId}
            editingChunkContent={chunkEditor === null ? '' : chunkEditor.content}
            onEditingChunkContentChange={changeChunkContent}
            onCancelEditChunk={cancelEditChunk}
            onSaveEditChunk={() => detachPromise(saveEditChunk())}
            canLoadMoreChunks={canLoadMoreChunks}
            onLoadMoreChunks={() => detachPromise(loadMoreChunks())}
            timelineItems={timelineItems}
            timelineTotal={timelineTotal}
            isLoadingTimeline={timelineQuery.isFetching}
            timelineError={timelineError}
            onLoadTimeline={() => timelineQuery.refetch()}
            timelineRowVirtualizer={timelineRowVirtualizer}
          />
        </main>

        {/* Footer */}
        <footer className="border-t border-foreground/15 bg-background px-6 py-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap gap-2">
              <DocumentVersionsDialog
                key={`versions:${metadataResourceKey}:${open}`}
                open={versionsDialogOpen}
                onOpenChange={handleVersionsDialogOpenChange}
                versions={versions}
                isLoading={versionsQuery.isFetching}
                error={versionsError}
                disabled={
                  metadataBusy || pendingChunkIds.size > 0 || !versionsQuery.isSuccess || versionsQuery.isFetching
                }
                onRefresh={handleVersionsRefresh}
                onCopy={handleCopyText}
                onActivate={(pipelineHash) => changeVersion('activate', pipelineHash)}
                onDelete={(pipelineHash) => changeVersion('delete', pipelineHash)}
              />

              <DocumentAccessDialog
                key={`access:${metadataResourceKey}:${open}`}
                open={accessDialogOpen}
                onOpenChange={handleAccessDialogOpenChange}
                access={accessInfo}
                loading={accessQuery.isFetching}
                loadError={accessLoadError}
                isSaving={isSavingAccess}
                metadataBusy={metadataBusy}
                onRetry={() => {
                  void accessQuery.refetch()
                }}
                onSave={saveAccess}
              />

              <DocumentDetailActions
                key={`actions:${metadataResourceKey}:${open}`}
                graphAction={pendingGraphRequests.get(metadataResourceKey)}
                downloadPending={pendingDownloads.has(metadataResourceKey)}
                canExtract={displayDoc.status === 'completed'}
                onExtractGraph={() => void changeDocumentGraph('extract')}
                onDeleteGraph={() => changeDocumentGraph('delete')}
                onDownloadCleanDocx={() => void downloadCleanDocx()}
              />
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
