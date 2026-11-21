'use client'

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { skipToken, useQuery, useQueryClient } from '@tanstack/react-query'

import { toast } from 'sonner'

import { formatApiError } from '@/lib/api-errors'
import { kgApi } from '@/lib/api/graph'
import { getAuthSessionKey } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import type { KGEntityAliasItem, KGEntityAliasSuggestionItem, KGGraphNode } from '@/types'

import { getGraphNodeKind, type GraphNodeLike } from './graph-page-utils'
import type { UseGraphDataLoadingResult } from './use-graph-data-loading'
import type { UseGraphPageStateResult } from './use-graph-page-state'

type UseGraphEntityResolutionParams = Readonly<{
  dataSource: 'live' | 'file'
  isDetailOpen: boolean
  selectedNode: GraphNodeLike | null
  scopeParams: UseGraphPageStateResult['scopeParams']
  loadLiveGraph: UseGraphDataLoadingResult['loadLiveGraph']
}>

export function useGraphEntityResolution({
  dataSource,
  isDetailOpen,
  selectedNode,
  scopeParams,
  loadLiveGraph,
}: UseGraphEntityResolutionParams) {
  const queryClient = useQueryClient()
  const [entityAliasDraft, setEntityAliasDraft] = useState<{ entityId: string; value: string } | null>(null)
  const [aliasSaving, setAliasSaving] = useState(false)
  const [aliasDeletion, setAliasDeletion] = useState<{ entityId: string; alias: KGEntityAliasItem } | null>(null)

  const [mergeOpen, setMergeOpen] = useState(false)
  const [mergeSearch, setMergeSearch] = useState('')
  const [mergeSearchLoading, setMergeSearchLoading] = useState(false)
  const [mergeSearchError, setMergeSearchError] = useState<string | null>(null)
  const [mergeSearchResults, setMergeSearchResults] = useState<KGGraphNode[]>([])
  const [mergeSelection, setMergeSelection] = useState<{ sourceId: string; target: KGGraphNode } | null>(null)
  const [mergeConfirmOpen, setMergeConfirmOpen] = useState(false)
  const [mergeSubmitting, setMergeSubmitting] = useState(false)

  const [splitEntityId, setSplitEntityId] = useState<string | null>(null)
  const [splitNameDraft, setSplitNameDraft] = useState('')
  const [splitSelectedEventIds, setSplitSelectedEventIds] = useState<Set<string>>(() => new Set())
  const [splitSubmitting, setSplitSubmitting] = useState(false)
  const [splitError, setSplitError] = useState<string | null>(null)

  const [lastResolutionActionId, setLastResolutionActionId] = useState<string | null>(null)
  const [undoSubmitting, setUndoSubmitting] = useState(false)
  const resolutionViewRef = useRef<object | null>(null)

  const selectedEntityId =
    dataSource === 'live' && selectedNode !== null && getGraphNodeKind(selectedNode) === 'entity'
      ? selectedNode.id
      : null
  const activeEntityId = isDetailOpen ? selectedEntityId : null

  useLayoutEffect(() => {
    resolutionViewRef.current = {}
    return () => {
      resolutionViewRef.current = null
    }
  }, [activeEntityId, dataSource, scopeParams, selectedEntityId])

  const captureResolutionView = useCallback(() => {
    const view = resolutionViewRef.current
    const sessionKey = getAuthSessionKey()
    return () => view !== null && resolutionViewRef.current === view && getAuthSessionKey() === sessionKey
  }, [])

  const mergeTarget = mergeSelection?.sourceId === selectedEntityId ? mergeSelection.target : null
  const mergeRequest =
    selectedEntityId === null || mergeTarget === null
      ? null
      : { source_entity_id: selectedEntityId, target_entity_id: mergeTarget.id }
  const mergePreviewQuery = useQuery({
    queryKey: queryKeys.kg.entityMergePreview(mergeRequest),
    queryFn:
      mergeOpen && mergeRequest !== null
        ? ({ signal }) => kgApi.previewMergeEntities(mergeRequest, { signal })
        : skipToken,
  })
  const mergeError =
    mergePreviewQuery.error === null ? null : formatApiError(mergePreviewQuery.error, '无法预览合并影响')

  const aliasListQuery = useQuery({
    queryKey: queryKeys.kg.entityAliases(activeEntityId),
    queryFn: activeEntityId === null ? skipToken : ({ signal }) => kgApi.listEntityAliases(activeEntityId, { signal }),
  })
  const aliasSuggestionsQuery = useQuery({
    queryKey: queryKeys.kg.entityAliasSuggestions(activeEntityId),
    queryFn:
      activeEntityId === null
        ? skipToken
        : ({ signal }) =>
            kgApi.suggestEntityAliases(activeEntityId, { mode: 'offline', k: 6, min_similarity: 0.75 }, { signal }),
  })
  const aliasDraft = entityAliasDraft?.entityId === activeEntityId ? entityAliasDraft.value : ''
  const aliasDeleteTarget = aliasDeletion?.entityId === activeEntityId ? aliasDeletion.alias : null

  function setAliasDraft(value: string) {
    if (activeEntityId !== null) setEntityAliasDraft({ entityId: activeEntityId, value })
  }

  const reloadEntityResolution = useCallback(
    async (entityId: string) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.kg.entityAliases(entityId), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.kg.entityAliasSuggestions(entityId), exact: true }),
      ])
    },
    [queryClient],
  )

  useEffect(() => {
    setEntityAliasDraft(null)
    setAliasDeletion(null)
    setSplitError(null)
    if (dataSource !== 'live') setLastResolutionActionId(null)
  }, [activeEntityId, dataSource])

  async function handleSaveAlias() {
    const alias = aliasDraft.trim()
    if (activeEntityId === null || aliasSaving) return
    if (alias === '') {
      toast.error('请输入 alias')
      return
    }

    const isCurrent = captureResolutionView()
    const sessionKey = getAuthSessionKey()
    setAliasSaving(true)
    try {
      await kgApi.createEntityAlias(activeEntityId, { alias })
      if (isCurrent()) {
        setEntityAliasDraft((current) =>
          current?.entityId === activeEntityId && current.value === aliasDraft ? null : current,
        )
        toast.success('已添加 alias')
      }
      if (getAuthSessionKey() === sessionKey) await reloadEntityResolution(activeEntityId)
    } catch (error) {
      if (isCurrent()) toast.error(formatApiError(error, '添加 alias 失败'))
    } finally {
      setAliasSaving(false)
    }
  }

  function requestDeleteAlias(row: KGEntityAliasItem) {
    if (activeEntityId !== null) setAliasDeletion({ entityId: activeEntityId, alias: row })
  }

  async function confirmDeleteAlias() {
    const deletion = aliasDeletion
    if (aliasSaving || deletion === null || deletion.entityId !== activeEntityId) return

    const isCurrent = captureResolutionView()
    const sessionKey = getAuthSessionKey()
    setAliasSaving(true)
    try {
      await kgApi.deleteEntityAlias(deletion.entityId, deletion.alias.id)
      if (isCurrent()) {
        setAliasDeletion((current) => (current === deletion ? null : current))
        toast.success('已删除 alias')
      }
      if (getAuthSessionKey() === sessionKey) await reloadEntityResolution(deletion.entityId)
    } catch (error) {
      if (isCurrent()) toast.error(formatApiError(error, '删除 alias 失败'))
    } finally {
      setAliasSaving(false)
    }
  }

  const openMergeDialog = useCallback(() => {
    setMergeOpen(true)
    setMergeSearch('')
    setMergeSearchResults([])
    setMergeSearchError(null)
    setMergeSelection(null)
  }, [])

  useEffect(() => {
    setMergeSearchError(null)
    if (!mergeOpen) {
      setMergeSearchLoading(false)
      return
    }
    const query = mergeSearch.trim()
    if (query.length < 2) {
      setMergeSearchResults([])
      setMergeSearchLoading(false)
      return
    }

    const controller = new AbortController()
    const { signal } = controller
    setMergeSearchLoading(true)

    const timer = globalThis.window.setTimeout(() => {
      ;(async () => {
        try {
          const rows = await kgApi.searchGraphNodes(
            {
              q: query,
              kind: 'entity',
              limit: 8,
              document_ids: scopeParams?.document_ids,
              pipeline_hash: scopeParams?.pipeline_hash,
            },
            { signal },
          )
          const filtered = rows.filter((row) => row.id !== selectedEntityId)
          if (!signal.aborted) setMergeSearchResults(filtered)
        } catch (error) {
          if (!signal.aborted) {
            setMergeSearchResults([])
            setMergeSearchError(formatApiError(error, '搜索实体失败'))
          }
        } finally {
          if (!signal.aborted) setMergeSearchLoading(false)
        }
      })()
    }, 250)

    return () => {
      controller.abort()
      globalThis.window.clearTimeout(timer)
    }
  }, [mergeOpen, mergeSearch, scopeParams, selectedEntityId])

  const selectMergeTarget = useCallback(
    (node: KGGraphNode) => {
      if (selectedEntityId === null || node.id === '') return
      setMergeSelection({ sourceId: selectedEntityId, target: node })
    },
    [selectedEntityId],
  )

  const handleMergeAliasSuggestion = useCallback(
    (suggestion: KGEntityAliasSuggestionItem) => {
      openMergeDialog()
      selectMergeTarget({
        id: suggestion.entity_id,
        label: suggestion.name === '' ? suggestion.entity_id : suggestion.name,
        meta: { kind: 'entity', type: suggestion.type },
      })
    },
    [openMergeDialog, selectMergeTarget],
  )

  async function submitMerge() {
    if (mergeRequest === null || mergeSubmitting) return

    const isCurrent = captureResolutionView()
    setMergeSubmitting(true)
    try {
      const out = await kgApi.mergeEntities(mergeRequest)
      if (!isCurrent()) return
      setLastResolutionActionId(out.action_id)
      toast.success('合并已完成（可撤销）')
      setMergeConfirmOpen(false)
      setMergeOpen(false)
      await loadLiveGraph()
      await reloadEntityResolution(mergeRequest.source_entity_id)
    } catch (error) {
      if (isCurrent()) toast.error(formatApiError(error, '合并失败'))
    } finally {
      setMergeSubmitting(false)
    }
  }

  const openSplitDialog = useCallback(() => {
    if (selectedEntityId === null || splitSubmitting) return
    setSplitEntityId(selectedEntityId)
    setSplitNameDraft('')
    setSplitSelectedEventIds(new Set())
    setSplitError(null)
  }, [selectedEntityId, splitSubmitting])

  const toggleSplitEvent = useCallback((eventId: string, checked: boolean) => {
    setSplitSelectedEventIds((prev) => {
      const next = new Set(prev)
      if (checked) next.add(eventId)
      else next.delete(eventId)
      return next
    })
  }, [])

  const submitSplit = useCallback(async () => {
    const name = splitNameDraft.trim()
    const eventIds = Array.from(splitSelectedEventIds)
    if (splitSubmitting || splitEntityId === null || splitEntityId !== selectedEntityId) return
    if (!name) {
      setSplitError('请输入新实体名称')
      return
    }
    if (eventIds.length === 0) {
      setSplitError('请选择要移动的事件（events）')
      return
    }

    const isCurrent = captureResolutionView()
    setSplitSubmitting(true)
    setSplitError(null)
    try {
      const out = await kgApi.splitEntity({
        entity_id: splitEntityId,
        new_entity_name: name,
        event_ids: eventIds,
      })
      if (!isCurrent()) return
      setLastResolutionActionId(out.action_id)
      toast.success('拆分已完成（可撤销）')
      setSplitEntityId((current) => (current === splitEntityId ? null : current))
      await loadLiveGraph()
      await reloadEntityResolution(splitEntityId)
    } catch (error) {
      if (isCurrent()) toast.error(formatApiError(error, '拆分失败'))
    } finally {
      setSplitSubmitting(false)
    }
  }, [
    captureResolutionView,
    loadLiveGraph,
    reloadEntityResolution,
    selectedEntityId,
    splitEntityId,
    splitNameDraft,
    splitSelectedEventIds,
    splitSubmitting,
  ])

  const undoLastResolution = useCallback(async () => {
    const actionId = lastResolutionActionId?.trim()
    if (actionId === undefined || actionId === '') return

    const isCurrent = captureResolutionView()
    setUndoSubmitting(true)
    try {
      const out = await kgApi.undoResolutionAction(actionId)
      if (!isCurrent()) return
      toast.success(`已撤销：${out.status}`)
      setLastResolutionActionId(null)
      await loadLiveGraph()
    } catch (error) {
      if (isCurrent()) toast.error(formatApiError(error, '撤销失败'))
    } finally {
      setUndoSubmitting(false)
    }
  }, [captureResolutionView, lastResolutionActionId, loadLiveGraph])

  const handleAliasDeleteOpenChange = useCallback(
    (open: boolean) => {
      if (!open && !aliasSaving) setAliasDeletion(null)
    },
    [aliasSaving],
  )

  const handleMergeOpenChange = useCallback((open: boolean) => {
    setMergeOpen(open)
    if (!open) {
      setMergeSearch('')
      setMergeSearchResults([])
      setMergeSelection(null)
      setMergeConfirmOpen(false)
    }
  }, [])

  const handleSplitOpenChange = useCallback(
    (open: boolean) => {
      if (!open && !splitSubmitting) {
        setSplitEntityId(null)
        setSplitNameDraft('')
        setSplitSelectedEventIds(new Set())
        setSplitError(null)
      }
    },
    [splitSubmitting],
  )

  return {
    entityAliases: aliasListQuery.data?.aliases ?? [],
    entityAliasesLoading: aliasListQuery.isFetching,
    entityAliasesError: aliasListQuery.error === null ? null : formatApiError(aliasListQuery.error, '读取别名失败'),
    aliasDraft,
    setAliasDraft,
    aliasSaving,
    aliasDeleteTarget,
    aliasSuggestions: aliasSuggestionsQuery.data?.suggestions ?? [],
    aliasSuggestionsLoading: aliasSuggestionsQuery.isFetching,
    aliasSuggestionsError:
      aliasSuggestionsQuery.error === null ? null : formatApiError(aliasSuggestionsQuery.error, '读取相似实体建议失败'),
    mergeOpen,
    mergeSearch,
    setMergeSearch,
    mergeSearchLoading,
    mergeSearchError,
    mergeSearchResults,
    mergeTarget,
    mergePreview: mergePreviewQuery.data ?? null,
    mergePreviewLoading: mergePreviewQuery.isFetching,
    mergeConfirmOpen,
    setMergeConfirmOpen,
    mergeSubmitting,
    mergeError,
    splitOpen: splitEntityId !== null && splitEntityId === selectedEntityId,
    splitNameDraft,
    setSplitNameDraft,
    splitSelectedEventIds,
    splitSubmitting,
    splitError,
    lastResolutionActionId,
    undoSubmitting,
    handleSaveAlias,
    requestDeleteAlias,
    confirmDeleteAlias,
    openMergeDialog,
    selectMergeTarget,
    handleMergeAliasSuggestion,
    submitMerge,
    openSplitDialog,
    toggleSplitEvent,
    submitSplit,
    undoLastResolution,
    handleAliasDeleteOpenChange,
    handleMergeOpenChange,
    handleSplitOpenChange,
  }
}

export type UseGraphEntityResolutionResult = ReturnType<typeof useGraphEntityResolution>
