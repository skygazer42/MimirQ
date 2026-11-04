'use client'

import { isCancelledError, keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'

import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { queryKeys } from '@/lib/query-keys'

import type {
  CaptureDocumentListOperation,
  DocumentListParams,
  DocumentListResponse,
  UpdateCachedDocuments,
} from './use-document-shared'

type UseDocumentListOptions = {
  setActionError: (error: string | null) => void
  initialParams?: DocumentListParams
}

const DEFAULT_LIST_PARAMS: DocumentListParams = {
  limit: 100,
  lifecycle: 'active',
}

function areDocumentListParamsEqual(a: DocumentListParams, b: DocumentListParams): boolean {
  return (
    a.skip === b.skip &&
    a.limit === b.limit &&
    a.status === b.status &&
    a.lifecycle === b.lifecycle &&
    a.dataset_id === b.dataset_id &&
    a.source_path_prefix === b.source_path_prefix &&
    a.q === b.q &&
    a.order_by === b.order_by &&
    a.order_dir === b.order_dir
  )
}

export function useDocumentList({ setActionError, initialParams = DEFAULT_LIST_PARAMS }: UseDocumentListOptions) {
  const queryClient = useQueryClient()
  const [listParams, setListParams] = useState<DocumentListParams>(initialParams)
  const lastListParamsRef = useRef<DocumentListParams>(initialParams)
  const previousInitialParamsRef = useRef<DocumentListParams>(initialParams)

  useEffect(() => {
    if (areDocumentListParamsEqual(previousInitialParamsRef.current, initialParams)) {
      return
    }

    previousInitialParamsRef.current = initialParams
    lastListParamsRef.current = initialParams
    setActionError(null)
    setListParams(initialParams)
  }, [initialParams, setActionError])

  const {
    data: listData,
    error: listError,
    isFetching,
    isLoading: isListLoading,
  } = useQuery<DocumentListResponse>({
    queryKey: queryKeys.documents.list(listParams),
    queryFn: ({ signal }) => documentApi.list(listParams, { signal }),
    placeholderData: (previousData, previousQuery) => {
      if (!previousQuery) return undefined
      return queryClient.getQueryCache().get<DocumentListResponse>(previousQuery.queryHash) === previousQuery
        ? keepPreviousData(previousData)
        : undefined
    },
  })

  const subscribeToQueryRemoval = useCallback(
    (onChange: () => void) =>
      queryClient.getQueryCache().subscribe((event) => {
        if (event.type === 'removed') onChange()
      }),
    [queryClient],
  )
  const getCurrentQuery = useCallback(
    () => queryClient.getQueryCache().find({ queryKey: queryKeys.documents.list(listParams), exact: true }),
    [listParams, queryClient],
  )
  const currentQuery = useSyncExternalStore(subscribeToQueryRemoval, getCurrentQuery, getCurrentQuery)
  useEffect(() => {
    setActionError(null)
  }, [currentQuery, setActionError])

  const fetchDocuments = useCallback(
    async (params: DocumentListParams) => {
      try {
        await queryClient.fetchQuery({
          queryKey: queryKeys.documents.list(params),
          queryFn: ({ signal }) => documentApi.list(params, { signal }),
        })
      } catch (err) {
        if (isCancelledError(err) || lastListParamsRef.current !== params) return
        setActionError(formatApiError(err, 'Failed to load documents'))
        reportClientError('Load documents failed', err)
      }
    },
    [queryClient, setActionError],
  )

  const captureDocumentListOperation = useCallback<CaptureDocumentListOperation>(() => {
    const params = lastListParamsRef.current
    const queryKey = queryKeys.documents.list(params)
    const query = queryClient.getQueryCache().find({ queryKey, exact: true })
    const isActive = () => query !== undefined && queryClient.getQueryCache().find({ queryKey, exact: true }) === query
    const isCurrent = () => isActive() && lastListParamsRef.current === params

    return {
      params,
      isActive,
      isCurrent,
      updateCachedDocuments: (updater) => {
        if (!isActive()) return
        queryClient.setQueryData<DocumentListResponse>(queryKey, updater)
      },
      refresh: async () => {
        if (!isActive()) return
        if (isCurrent()) setActionError(null)
        await fetchDocuments(params)
      },
    }
  }, [fetchDocuments, queryClient, setActionError])

  const updateCachedDocuments = useCallback<UpdateCachedDocuments>(
    (updater) => captureDocumentListOperation().updateCachedDocuments(updater),
    [captureDocumentListOperation],
  )

  const loadDocuments = useCallback(
    async (params?: DocumentListParams) => {
      setActionError(null)

      const effective = params ? { ...lastListParamsRef.current, ...params } : { ...lastListParamsRef.current }

      lastListParamsRef.current = effective
      setListParams(effective)

      await fetchDocuments(effective)
    },
    [fetchDocuments, setActionError],
  )

  return {
    documents: listData?.items || [],
    total: Number(listData?.total) || 0,
    listError,
    isFetching,
    isListLoading,
    loadDocuments,
    lastListParamsRef,
    updateCachedDocuments,
    captureDocumentListOperation,
  }
}
