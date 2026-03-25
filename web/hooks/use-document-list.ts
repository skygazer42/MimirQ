'use client'

import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useRef, useState } from 'react'

import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'

import type { DocumentListParams, DocumentListResponse, UpdateCachedDocuments } from './use-document-shared'

type UseDocumentListOptions = {
  setActionError: (error: string | null) => void
  initialParams?: DocumentListParams
}

const DEFAULT_LIST_PARAMS: DocumentListParams = {
  limit: 100,
  lifecycle: 'active',
}

export function useDocumentList({
  setActionError,
  initialParams = DEFAULT_LIST_PARAMS,
}: UseDocumentListOptions) {
  const queryClient = useQueryClient()
  const [listParams, setListParams] = useState<DocumentListParams>(initialParams)
  const lastListParamsRef = useRef<DocumentListParams>(initialParams)

  const {
    data: listData,
    error: listError,
    isFetching,
    isLoading: isListLoading,
  } = useQuery<DocumentListResponse>({
    queryKey: queryKeys.documents.list(listParams),
    queryFn: () => documentApi.list(listParams),
    placeholderData: keepPreviousData,
  })

  const updateCachedDocuments = useCallback<UpdateCachedDocuments>(
    (updater) => {
      queryClient.setQueryData<DocumentListResponse>(
        queryKeys.documents.list(lastListParamsRef.current),
        updater
      )
    },
    [queryClient]
  )

  const loadDocuments = useCallback(
    async (params?: DocumentListParams) => {
      setActionError(null)

      const effective = params
        ? { ...lastListParamsRef.current, ...params }
        : { ...lastListParamsRef.current }

      lastListParamsRef.current = effective
      setListParams(effective)

      try {
        await queryClient.fetchQuery({
          queryKey: queryKeys.documents.list(effective),
          queryFn: () => documentApi.list(effective),
        })
      } catch (err) {
        setActionError(formatApiError(err, 'Failed to load documents'))
        console.error('Load documents error:', err)
      }
    },
    [queryClient, setActionError]
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
  }
}
