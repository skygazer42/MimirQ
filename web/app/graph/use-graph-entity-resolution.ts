'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { toast } from 'sonner'

import { formatApiError } from '@/lib/api-errors'
import { kgApi } from '@/lib/api/graph'
import type {
  KGEntityAliasItem,
  KGEntityAliasSuggestionItem,
  KGEntityMergePreviewResponse,
  KGGraphNode,
} from '@/types'

import type { GraphNodeLike } from './graph-page-utils'

type GraphScopeParams = Readonly<{
  document_ids?: string[]
  pipeline_hash?: string
}> | null

type GraphLoadOptions = Readonly<{
  includeEntityLinks?: boolean
  includeRelationLinks?: boolean
  minSharedEvents?: number
}>

type UseGraphEntityResolutionParams = Readonly<{
  dataSource: 'live' | 'file'
  isDetailOpen: boolean
  selectedNode: GraphNodeLike | null
  scopeParams: GraphScopeParams
  loadInitialData: (source?: 'live', opts?: GraphLoadOptions) => Promise<void>
}>

export function useGraphEntityResolution({
  dataSource,
  isDetailOpen,
  selectedNode,
  scopeParams,
  loadInitialData,
}: UseGraphEntityResolutionParams) {
  const [entityAliases, setEntityAliases] = useState<KGEntityAliasItem[]>([])
  const [entityAliasesLoading, setEntityAliasesLoading] = useState(false)
  const [aliasDraft, setAliasDraft] = useState('')
  const [aliasSaving, setAliasSaving] = useState(false)
  const [aliasDeleteOpen, setAliasDeleteOpen] = useState(false)
  const [aliasDeleteTarget, setAliasDeleteTarget] = useState<KGEntityAliasItem | null>(null)

  const [aliasSuggestions, setAliasSuggestions] = useState<KGEntityAliasSuggestionItem[]>([])
  const [aliasSuggestionsLoading, setAliasSuggestionsLoading] = useState(false)

  const [mergeOpen, setMergeOpen] = useState(false)
  const [mergeSearch, setMergeSearch] = useState('')
  const [mergeSearchLoading, setMergeSearchLoading] = useState(false)
  const [mergeSearchResults, setMergeSearchResults] = useState<KGGraphNode[]>([])
  const [mergeTarget, setMergeTarget] = useState<KGGraphNode | null>(null)
  const [mergePreview, setMergePreview] = useState<KGEntityMergePreviewResponse | null>(null)
  const [mergePreviewLoading, setMergePreviewLoading] = useState(false)
  const [mergeConfirmOpen, setMergeConfirmOpen] = useState(false)
  const [mergeSubmitting, setMergeSubmitting] = useState(false)
  const [mergeError, setMergeError] = useState<string | null>(null)

  const [splitOpen, setSplitOpen] = useState(false)
  const [splitNameDraft, setSplitNameDraft] = useState('')
  const [splitSelectedEventIds, setSplitSelectedEventIds] = useState<Set<string>>(new Set())
  const [splitSubmitting, setSplitSubmitting] = useState(false)
  const [splitError, setSplitError] = useState<string | null>(null)

  const [lastResolutionActionId, setLastResolutionActionId] = useState<string | null>(null)
  const [undoSubmitting, setUndoSubmitting] = useState(false)

  const selectedEntityId = useMemo(() => {
    return selectedNode?.meta?.kind === 'entity' ? String(selectedNode.id || '') : ''
  }, [selectedNode])

  const reloadEntityResolution = useCallback(async (entityId: string) => {
    try {
      setEntityAliasesLoading(true)
      const resp = await kgApi.listEntityAliases(entityId)
      setEntityAliases(resp.aliases || [])
    } catch {
      setEntityAliases([])
    } finally {
      setEntityAliasesLoading(false)
    }

    try {
      setAliasSuggestionsLoading(true)
      const resp = await kgApi.suggestEntityAliases(entityId, { mode: 'offline', k: 6, min_similarity: 0.75 })
      setAliasSuggestions(resp.suggestions || [])
    } catch {
      setAliasSuggestions([])
    } finally {
      setAliasSuggestionsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (dataSource !== 'live') {
      setEntityAliases([])
      setAliasSuggestions([])
      setAliasDraft('')
      setLastResolutionActionId(null)
      return
    }

    if (!isDetailOpen || !selectedEntityId) {
      setEntityAliases([])
      setAliasSuggestions([])
      setAliasDraft('')
      return
    }

    let cancelled = false

    setEntityAliasesLoading(true)
    setAliasSuggestionsLoading(true)
    setMergeError(null)
    setSplitError(null)

    ;(async () => {
      try {
        const resp = await kgApi.listEntityAliases(selectedEntityId)
        if (!cancelled) setEntityAliases(resp.aliases || [])
      } catch {
        if (!cancelled) setEntityAliases([])
      } finally {
        if (!cancelled) setEntityAliasesLoading(false)
      }
    })()

    ;(async () => {
      try {
        const resp = await kgApi.suggestEntityAliases(selectedEntityId, {
          mode: 'offline',
          k: 6,
          min_similarity: 0.75,
        })
        if (!cancelled) setAliasSuggestions(resp.suggestions || [])
      } catch {
        if (!cancelled) setAliasSuggestions([])
      } finally {
        if (!cancelled) setAliasSuggestionsLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [dataSource, isDetailOpen, selectedEntityId])

  const handleSaveAlias = useCallback(async () => {
    const alias = aliasDraft.trim()
    if (!selectedEntityId) return
    if (!alias) {
      toast.error('请输入 alias')
      return
    }

    setAliasSaving(true)
    try {
      await kgApi.createEntityAlias(selectedEntityId, { alias })
      setAliasDraft('')
      toast.success('已添加 alias')
      await reloadEntityResolution(selectedEntityId)
    } catch (error) {
      toast.error(formatApiError(error, '添加 alias 失败'))
    } finally {
      setAliasSaving(false)
    }
  }, [aliasDraft, reloadEntityResolution, selectedEntityId])

  const requestDeleteAlias = useCallback((row: KGEntityAliasItem) => {
    setAliasDeleteTarget(row)
    setAliasDeleteOpen(true)
  }, [])

  const confirmDeleteAlias = useCallback(async () => {
    const aliasId = aliasDeleteTarget?.id ? String(aliasDeleteTarget.id) : ''
    if (!selectedEntityId || !aliasId) {
      setAliasDeleteOpen(false)
      setAliasDeleteTarget(null)
      return
    }

    setAliasSaving(true)
    try {
      const resp = await kgApi.deleteEntityAlias(selectedEntityId, aliasId)
      setEntityAliases(resp.aliases || [])
      toast.success('已删除 alias')
      await reloadEntityResolution(selectedEntityId)
    } catch (error) {
      toast.error(formatApiError(error, '删除 alias 失败'))
    } finally {
      setAliasSaving(false)
      setAliasDeleteOpen(false)
      setAliasDeleteTarget(null)
    }
  }, [aliasDeleteTarget, reloadEntityResolution, selectedEntityId])

  const openMergeDialog = useCallback(() => {
    setMergeOpen(true)
    setMergeSearch('')
    setMergeSearchResults([])
    setMergeTarget(null)
    setMergePreview(null)
    setMergeError(null)
  }, [])

  useEffect(() => {
    if (!mergeOpen) return
    const query = mergeSearch.trim()
    if (query.length < 2) {
      setMergeSearchResults([])
      return
    }

    let cancelled = false
    setMergeSearchLoading(true)

    const timer = globalThis.window.setTimeout(() => {
      ;(async () => {
        try {
          const rows = await kgApi.searchGraphNodes({
            q: query,
            kind: 'entity',
            limit: 8,
            document_ids: scopeParams?.document_ids,
            pipeline_hash: scopeParams?.pipeline_hash,
          })
          const filtered = (rows || []).filter((row) => String(row.id) !== selectedEntityId)
          if (!cancelled) setMergeSearchResults(filtered)
        } catch {
          if (!cancelled) setMergeSearchResults([])
        } finally {
          if (!cancelled) setMergeSearchLoading(false)
        }
      })()
    }, 250)

    return () => {
      cancelled = true
      globalThis.window.clearTimeout(timer)
    }
  }, [mergeOpen, mergeSearch, scopeParams, selectedEntityId])

  const selectMergeTarget = useCallback(
    async (node: KGGraphNode) => {
      const targetId = String(node?.id || '')
      if (!selectedEntityId || !targetId) return

      setMergeTarget(node)
      setMergePreview(null)
      setMergeError(null)
      setMergePreviewLoading(true)
      try {
        const preview = await kgApi.previewMergeEntities({
          source_entity_id: selectedEntityId,
          target_entity_id: targetId,
        })
        setMergePreview(preview)
      } catch (error) {
        setMergeError(formatApiError(error, '无法预览合并影响'))
        setMergePreview(null)
      } finally {
        setMergePreviewLoading(false)
      }
    },
    [selectedEntityId]
  )

  const handleMergeAliasSuggestion = useCallback(
    (suggestion: KGEntityAliasSuggestionItem) => {
      openMergeDialog()
      void selectMergeTarget({
        id: suggestion.entity_id,
        label: suggestion.name || suggestion.entity_id,
        meta: { kind: 'entity', type: suggestion.type },
      })
    },
    [openMergeDialog, selectMergeTarget]
  )

  const submitMerge = useCallback(async () => {
    const targetId = String(mergeTarget?.id || '')
    if (!selectedEntityId || !targetId) return

    setMergeSubmitting(true)
    setMergeError(null)
    try {
      const out = await kgApi.mergeEntities({
        source_entity_id: selectedEntityId,
        target_entity_id: targetId,
      })
      setLastResolutionActionId(String(out.action_id))
      toast.success('合并已完成（可撤销）')
      setMergeConfirmOpen(false)
      setMergeOpen(false)
      await loadInitialData('live')
      await reloadEntityResolution(selectedEntityId)
    } catch (error) {
      setMergeError(formatApiError(error, '合并失败'))
    } finally {
      setMergeSubmitting(false)
    }
  }, [loadInitialData, mergeTarget, reloadEntityResolution, selectedEntityId])

  const openSplitDialog = useCallback(() => {
    setSplitOpen(true)
    setSplitNameDraft('')
    setSplitSelectedEventIds(new Set())
    setSplitError(null)
  }, [])

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
    if (!selectedEntityId) return
    if (!name) {
      setSplitError('请输入新实体名称')
      return
    }
    if (eventIds.length === 0) {
      setSplitError('请选择要移动的事件（events）')
      return
    }

    setSplitSubmitting(true)
    setSplitError(null)
    try {
      const out = await kgApi.splitEntity({
        entity_id: selectedEntityId,
        new_entity_name: name,
        event_ids: eventIds,
      })
      setLastResolutionActionId(String(out.action_id))
      toast.success('拆分已完成（可撤销）')
      setSplitOpen(false)
      await loadInitialData('live')
      await reloadEntityResolution(selectedEntityId)
    } catch (error) {
      setSplitError(formatApiError(error, '拆分失败'))
    } finally {
      setSplitSubmitting(false)
    }
  }, [loadInitialData, reloadEntityResolution, selectedEntityId, splitNameDraft, splitSelectedEventIds])

  const undoLastResolution = useCallback(async () => {
    const actionId = (lastResolutionActionId || '').trim()
    if (!actionId) return

    setUndoSubmitting(true)
    try {
      const out = await kgApi.undoResolutionAction(actionId)
      toast.success(`已撤销：${String(out.status || 'ok')}`)
      setLastResolutionActionId(null)
      await loadInitialData('live')
    } catch (error) {
      toast.error(formatApiError(error, '撤销失败'))
    } finally {
      setUndoSubmitting(false)
    }
  }, [lastResolutionActionId, loadInitialData])

  const handleAliasDeleteOpenChange = useCallback((open: boolean) => {
    setAliasDeleteOpen(open)
    if (!open) setAliasDeleteTarget(null)
  }, [])

  const handleMergeOpenChange = useCallback((open: boolean) => {
    setMergeOpen(open)
    if (!open) {
      setMergeSearch('')
      setMergeSearchResults([])
      setMergeTarget(null)
      setMergePreview(null)
      setMergeError(null)
      setMergeConfirmOpen(false)
    }
  }, [])

  const handleSplitOpenChange = useCallback((open: boolean) => {
    setSplitOpen(open)
    if (!open) {
      setSplitNameDraft('')
      setSplitSelectedEventIds(new Set())
      setSplitError(null)
    }
  }, [])

  return {
    entityAliases,
    entityAliasesLoading,
    aliasDraft,
    setAliasDraft,
    aliasSaving,
    aliasDeleteOpen,
    aliasDeleteTarget,
    aliasSuggestions,
    aliasSuggestionsLoading,
    mergeOpen,
    mergeSearch,
    setMergeSearch,
    mergeSearchLoading,
    mergeSearchResults,
    mergeTarget,
    mergePreview,
    mergePreviewLoading,
    mergeConfirmOpen,
    setMergeConfirmOpen,
    mergeSubmitting,
    mergeError,
    splitOpen,
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
