'use client'

import { hashKey, isCancelledError, queryOptions, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'

import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey } from '@/lib/auth-storage'
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
const EMPTY_DOCUMENTS: DocumentListResponse['items'] = []

function areDocumentListParamsEqual(a: DocumentListParams, b: DocumentListParams): boolean {
  return a === b || hashKey(queryKeys.documents.list(a)) === hashKey(queryKeys.documents.list(b))
}

function documentListOptions(params: DocumentListParams) {
  return queryOptions({
    queryKey: queryKeys.documents.list(params),
    queryFn: ({ signal }) => documentApi.list(params, { signal }),
  })
}

export function useDocumentList({ setActionError, initialParams = DEFAULT_LIST_PARAMS }: UseDocumentListOptions) {
  const queryClient = useQueryClient()
  const [listParams, setListParams] = useState<DocumentListParams>(initialParams)
  const lastListParamsRef = useRef<DocumentListParams>(initialParams)
  const previousInitialParamsRef = useRef<DocumentListParams>(initialParams)

  useLayoutEffect(() => {
    if (areDocumentListParamsEqual(previousInitialParamsRef.current, initialParams)) {
      return
    }

    previousInitialParamsRef.current = initialParams
    if (areDocumentListParamsEqual(lastListParamsRef.current, initialParams)) return

    lastListParamsRef.current = initialParams
    setActionError(null)
    setListParams(initialParams)
  }, [initialParams, setActionError])

  const {
    data: listData,
    error: listError,
    isFetching,
    isPlaceholderData,
    isLoading: isListLoading,
  } = useQuery({
    ...documentListOptions(listParams),
    placeholderData: (previousData, previousQuery) => {
      if (!previousQuery) return undefined
      const cachedQuery: object | undefined = queryClient.getQueryCache().get(previousQuery.queryHash)
      return cachedQuery === previousQuery ? previousData : undefined
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
  useLayoutEffect(() => {
    setActionError(null)
  }, [currentQuery, setActionError])

  const fetchDocuments = useCallback(
    async (params: DocumentListParams) => {
      const sessionKey = getAuthSessionKey()
      const options = documentListOptions(params)
      const { queryKey } = options
      const cache = queryClient.getQueryCache()
      const request = queryClient.fetchQuery({ ...options, staleTime: 0 })
      const query = cache.find({ queryKey, exact: true })
      try {
        await request
      } catch (error) {
        if (
          isCancelledError(error) ||
          sessionKey !== getAuthSessionKey() ||
          lastListParamsRef.current !== params ||
          query === undefined ||
          cache.find({ queryKey, exact: true }) !== query
        )
          return
        setActionError(formatApiError(error, 'Failed to load documents'))
        reportClientError('Load documents failed', error)
      }
    },
    [queryClient, setActionError],
  )

  const captureDocumentListOperation = useCallback<CaptureDocumentListOperation>(() => {
    const sessionKey = getAuthSessionKey()
    const params = lastListParamsRef.current
    const queryKey = queryKeys.documents.list(params)
    const query = queryClient.getQueryCache().find({ queryKey, exact: true })
    const isActive = () =>
      sessionKey === getAuthSessionKey() &&
      query !== undefined &&
      queryClient.getQueryCache().find({ queryKey, exact: true }) === query
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

      const current = lastListParamsRef.current
      const merged = params === undefined ? current : { ...current, ...params }
      const effective = areDocumentListParamsEqual(current, merged) ? current : merged
      if (effective !== current) {
        lastListParamsRef.current = effective
        setListParams(effective)
      }
      await fetchDocuments(effective)
    },
    [fetchDocuments, setActionError],
  )

  return {
    documents: listData === undefined ? EMPTY_DOCUMENTS : listData.items,
    total: listData === undefined ? 0 : listData.total,
    listError,
    isFetching,
    isPlaceholderData,
    isListLoading,
    loadDocuments,
    lastListParamsRef,
    updateCachedDocuments,
    captureDocumentListOperation,
  }
}
