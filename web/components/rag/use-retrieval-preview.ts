'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Citation, EvidenceRetrieveRequest, EvidenceRetrieveResponse } from '@/types'
import { ragApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'

export type RetrievePreviewCitation = Partial<Omit<Citation, 'matched_terms' | 'policy_clause_number' | 'policy_path_str'>> & {
  document_id?: string
  document_name?: string
  chunk_id?: string
  chunk_content?: string
  matched_terms?: unknown
  retrieval_role?: string | null
  family_hit?: boolean | null
  has_image?: boolean | null
  img_url?: string | null
  file_url?: string | null
  score?: number | null
  text_range?: { start?: number; end?: number } | null
  policy_clause_number?: string | null
  policy_path_str?: string | null
}

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
  availableDatasetIds: readonly string[]
): Pick<EvidenceRetrieveRequest, 'dataset_id' | 'dataset_ids'> {
  const selected = String(selectedDatasetId || '').trim()
  if (selected) return { dataset_id: selected }
  const ids = [...new Set(availableDatasetIds.map(id => String(id || '').trim()).filter(Boolean))]
  return ids.length ? { dataset_ids: ids } : {}
}

function normalizeCitations(response: EvidenceRetrieveResponse): RetrievePreviewCitation[] {
  return Array.isArray(response.citations)
    ? response.citations.filter(citation => typeof citation === 'object' && citation !== null && !Array.isArray(citation)) as RetrievePreviewCitation[]
    : []
}

type PreviewState = { scopeKey: string; run: RetrievalRun | null; isSearching: boolean; error: string | null }
const EMPTY_DATASET_IDS: readonly string[] = []

export function useRetrievalPreview(selectedDatasetId: string | null | undefined, availableDatasetIds = EMPTY_DATASET_IDS) {
  const scope = useMemo(() => buildRetrieveDatasetScope(selectedDatasetId, availableDatasetIds), [selectedDatasetId, availableDatasetIds])
  const scopeKey = JSON.stringify(scope.dataset_id ?? [...(scope.dataset_ids ?? [])].sort())
  const [draft, setDraft] = useState('')
  const [history, setHistory] = useState<RetrievalRun[]>([])
  const [state, setState] = useState<PreviewState>({ scopeKey, run: null, isSearching: false, error: null })
  const requestRef = useRef(0)
  const inFlightRef = useRef(false)
  const view = state.scopeKey === scopeKey ? state : { scopeKey, run: null, isSearching: false, error: null }
  const hasScope = Boolean(scope.dataset_id || scope.dataset_ids?.length)

  useEffect(() => {
    requestRef.current += 1
    inFlightRef.current = false
    setState(previous => previous.scopeKey === scopeKey ? previous : { scopeKey, run: null, isSearching: false, error: null })
    return () => {
      requestRef.current += 1
      inFlightRef.current = false
    }
  }, [scopeKey])

  const search = useCallback(async () => {
    const query = draft.trim()
    if (!query || inFlightRef.current) return
    if (!hasScope) {
      setState({ scopeKey, run: null, isSearching: false, error: '暂无可检索数据集，请先导入文档。' })
      return
    }
    const requestId = ++requestRef.current
    inFlightRef.current = true
    const startedAt = Date.now()
    setState({ scopeKey, run: null, isSearching: true, error: null })
    try {
      const response = await ragApi.retrieveEvidence({
        query,
        ...scope,
        // Omitting this field applies the endpoint's recall50 diagnostic profile;
        // an empty config uses saved runtime defaults and dataset overrides.
        rag_config: {},
      })
      if (requestId !== requestRef.current) return
      const run: RetrievalRun = {
        id: requestId, scopeKey, query,
        queryForRetrieval: String(response.query_for_retrieval || query),
        hits: normalizeCitations(response), timestamp: Date.now(), durationMs: Date.now() - startedAt,
      }
      setState({ scopeKey, run, isSearching: false, error: null })
      setHistory(previous => [run, ...previous.filter(item => item.scopeKey !== scopeKey || item.query !== query)].slice(0, 30))
    } catch (error) {
      if (requestId !== requestRef.current) return
      setState({ scopeKey, run: null, isSearching: false, error: formatApiError(error, '检索失败，请重试。') })
    } finally {
      if (requestId === requestRef.current) inFlightRef.current = false
    }
  }, [draft, hasScope, scope, scopeKey])

  const restore = useCallback((run: RetrievalRun) => {
    if (run.scopeKey !== scopeKey || inFlightRef.current) return
    setDraft(run.query)
    setState({ scopeKey, run, isSearching: false, error: null })
  }, [scopeKey])

  return {
    draft, setDraft, search, restore, hasScope,
    run: view.run, isSearching: view.isSearching, error: view.error,
    history: history.filter(item => item.scopeKey === scopeKey),
    clearHistory: () => setHistory(previous => previous.filter(item => item.scopeKey !== scopeKey)),
  }
}
