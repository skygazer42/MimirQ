'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { EvidenceRetrieveRequest } from '@/types'
import { ragApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { retrievalPreviewCitationsSchema, type RetrievePreviewCitation } from '@/lib/citations'

export type RetrievalRun = {
  id: number
  scopeKey: string
  query: string
  queryForRetrieval: string
  hits: RetrievePreviewCitation[]
  timestamp: number
  durationMs: number
}

export function buildRetrieveDatasetScope(
  selectedDatasetId: string | null | undefined,
  availableDatasetIds: readonly string[],
): Pick<EvidenceRetrieveRequest, 'dataset_id' | 'dataset_ids'> {
  const selected = selectedDatasetId?.trim()
  if (selected !== undefined && selected !== '') return { dataset_id: selected }
  const ids = [...new Set(availableDatasetIds.map((id) => id.trim()).filter((id) => id !== ''))]
  return ids.length > 0 ? { dataset_ids: ids } : {}
}

type PreviewState = { scopeKey: string; run: RetrievalRun | null; isSearching: boolean; error: string | null }
const EMPTY_DATASET_IDS: readonly string[] = []
const RETRIEVAL_SCOPE_MAX_DATASET_IDS = 80

export function useRetrievalPreview(
  selectedDatasetId: string | null | undefined,
  availableDatasetIds = EMPTY_DATASET_IDS,
) {
  const scope = useMemo(
    () => buildRetrieveDatasetScope(selectedDatasetId, availableDatasetIds),
    [selectedDatasetId, availableDatasetIds],
  )
  const scopeKey = JSON.stringify(scope.dataset_id ?? [...(scope.dataset_ids ?? [])].sort())
  const [draft, setDraft] = useState('')
  const [history, setHistory] = useState<RetrievalRun[]>([])
  const [state, setState] = useState<PreviewState>({ scopeKey, run: null, isSearching: false, error: null })
  const runSequenceRef = useRef(0)
  const activeRequestRef = useRef<AbortController | null>(null)
  const view = state.scopeKey === scopeKey ? state : { scopeKey, run: null, isSearching: false, error: null }
  const hasScope = scope.dataset_id !== undefined || scope.dataset_ids !== undefined
  const scopeError =
    scope.dataset_ids !== undefined && scope.dataset_ids.length > RETRIEVAL_SCOPE_MAX_DATASET_IDS
      ? `每次检索最多支持 ${RETRIEVAL_SCOPE_MAX_DATASET_IDS} 个数据集。请选择一个数据集。`
      : null

  useEffect(() => {
    setState((previous) =>
      previous.scopeKey === scopeKey ? previous : { scopeKey, run: null, isSearching: false, error: null },
    )
    return () => {
      activeRequestRef.current?.abort()
      activeRequestRef.current = null
    }
  }, [scopeKey])

  const search = useCallback(async () => {
    const query = draft.trim()
    if (query === '' || scopeError !== null || activeRequestRef.current !== null) return
    if (!hasScope) {
      setState({ scopeKey, run: null, isSearching: false, error: '暂无可检索数据集，请先导入文档。' })
      return
    }
    const request = new AbortController()
    activeRequestRef.current = request
    const startedAt = Date.now()
    setState({ scopeKey, run: null, isSearching: true, error: null })
    try {
      const response = await ragApi.retrieveEvidence(
        {
          query,
          ...scope,
          // Omitting this field applies the endpoint's recall50 diagnostic profile;
          // an empty config uses saved runtime defaults and dataset overrides.
          rag_config: {},
        },
        { signal: request.signal },
      )
      if (activeRequestRef.current !== request) return
      const run: RetrievalRun = {
        id: ++runSequenceRef.current,
        scopeKey,
        query,
        queryForRetrieval: response.query_for_retrieval,
        hits: retrievalPreviewCitationsSchema.parse(response.citations),
        timestamp: Date.now(),
        durationMs: Date.now() - startedAt,
      }
      setState({ scopeKey, run, isSearching: false, error: null })
      setHistory((previous) =>
        [run, ...previous.filter((item) => item.scopeKey !== scopeKey || item.query !== query)].slice(0, 30),
      )
    } catch (error) {
      if (activeRequestRef.current !== request) return
      setState({ scopeKey, run: null, isSearching: false, error: formatApiError(error, '检索失败，请重试。') })
    } finally {
      if (activeRequestRef.current === request) activeRequestRef.current = null
    }
  }, [draft, hasScope, scope, scopeError, scopeKey])

  const restore = useCallback(
    (run: RetrievalRun) => {
      if (run.scopeKey !== scopeKey || activeRequestRef.current !== null) return
      setDraft(run.query)
      setState({ scopeKey, run, isSearching: false, error: null })
    },
    [scopeKey],
  )

  return {
    draft,
    setDraft,
    search,
    restore,
    hasScope,
    scopeError,
    run: view.run,
    isSearching: view.isSearching,
    error: view.error,
    history: history.filter((item) => item.scopeKey === scopeKey),
    clearHistory: () => setHistory((previous) => previous.filter((item) => item.scopeKey !== scopeKey)),
  }
}
