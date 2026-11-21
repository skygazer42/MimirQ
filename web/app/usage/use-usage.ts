'use client'

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { queryOptions, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import type { Dataset } from '@/types'
import type { ChatCostUsageSummary, ChatTokenUsageSummary } from '@/types/usage'
import { datasetApi } from '@/lib/api/datasets'
import { usageApi } from '@/lib/api/usage'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import { buildQuotaReadings, buildUsageRows, parseUsageLocation } from './usage-model'

type UsageSnapshot<T> = Readonly<{ windowDays: number; data: T; receivedAt: number }>
const READ_NOW = { staleTime: 0, retry: false, networkMode: 'always' } as const

function selectDatasetNames(datasets: readonly Dataset[]): Map<string, string> {
  return new Map(datasets.map((dataset) => [dataset.id, dataset.name]))
}

async function readUsageSnapshot<T>(windowDays: number, request: Promise<T>): Promise<UsageSnapshot<T>> {
  const data = await request
  return { windowDays, data, receivedAt: Date.now() }
}

export function useUsage(sessionKey: string) {
  const search = useSearchParams().toString()
  const scope = useMemo(() => parseUsageLocation(search), [search])
  const { windowDays, view } = scope
  const queryClient = useQueryClient()
  const prefix = ['usage', sessionKey] as const
  const params = { window_days: windowDays }
  const summaryOptions = queryOptions({
    queryKey: [...prefix, 'summary', windowDays],
    queryFn: ({ signal }) => readUsageSnapshot(windowDays, usageApi.getChatTokenUsageSummary(params, { signal })),
  })
  const costOptions = queryOptions({
    queryKey: [...prefix, 'cost', windowDays],
    queryFn: ({ signal }) => readUsageSnapshot(windowDays, usageApi.getChatCostUsageSummary(params, { signal })),
  })
  const chatQuotaOptions = queryOptions({
    queryKey: [...prefix, 'quota'],
    queryFn: ({ signal }) => usageApi.getChatTokenQuotaStatus({ signal }),
    staleTime: 60_000,
  })
  const tenantQuotaOptions = queryOptions({
    queryKey: [...prefix, 'tenant-quota-summary'],
    queryFn: ({ signal }) => usageApi.getTenantQuotaSummary({ signal }),
    staleTime: 60_000,
  })
  const datasetOptions = queryOptions({
    queryKey: queryKeys.datasets.exhaustive(),
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
    staleTime: 300_000,
  })
  const summaryQuery = useQuery(summaryOptions)
  const costQuery = useQuery(costOptions)
  const chatQuotaQuery = useQuery(chatQuotaOptions)
  const tenantQuotaQuery = useQuery(tenantQuotaOptions)
  const labelsQuery = useQuery({
    ...datasetOptions,
    select: selectDatasetNames,
  })
  const [acceptedSummary, setAcceptedSummary] = useState<UsageSnapshot<ChatTokenUsageSummary> | undefined>()
  const [acceptedCost, setAcceptedCost] = useState<UsageSnapshot<ChatCostUsageSummary> | undefined>()
  useEffect(() => {
    if (summaryQuery.data !== undefined) setAcceptedSummary(summaryQuery.data)
  }, [summaryQuery.data])
  useEffect(() => {
    if (costQuery.data !== undefined) setAcceptedCost(costQuery.data)
  }, [costQuery.data])
  const summarySnapshot = summaryQuery.data === undefined && summaryQuery.isError ? acceptedSummary : summaryQuery.data
  const costSnapshot = costQuery.data === undefined && costQuery.isError ? acceptedCost : costQuery.data
  const summary = summarySnapshot?.data
  const cost = costSnapshot?.data
  const labelState = labelsQuery.isError ? 'error' : labelsQuery.isSuccess ? 'ready' : 'pending'
  const attributionSnapshot = summaryQuery.data ?? costQuery.data ?? summarySnapshot ?? costSnapshot
  const attributionWindowDays = attributionSnapshot?.windowDays ?? windowDays
  const attributionSummary = summarySnapshot?.windowDays === attributionWindowDays ? summary : undefined
  const attributionCost = costSnapshot?.windowDays === attributionWindowDays ? cost : undefined
  const tableSummary = view === 'attribution' ? attributionSummary : undefined
  const tableCost = view === 'attribution' ? attributionCost : view === 'resources' ? cost : undefined
  const rows = useMemo(
    () => buildUsageRows(tableSummary, tableCost, labelsQuery.data, labelState),
    [tableSummary, tableCost, labelsQuery.data, labelState],
  )
  const quotas = useMemo(
    () => buildQuotaReadings(chatQuotaQuery.data, tenantQuotaQuery.data),
    [chatQuotaQuery.data, tenantQuotaQuery.data],
  )
  const quotaPending = { chat: chatQuotaQuery.isPending, tenant: tenantQuotaQuery.isPending }
  const rawQuota = JSON.stringify(
    { chat_token_quota: chatQuotaQuery.data, tenant_quotas: tenantQuotaQuery.data },
    null,
    2,
  )
  const hasQuotaData = chatQuotaQuery.data !== undefined || tenantQuotaQuery.data !== undefined
  const reads = [
    {
      label: '助手用量',
      query: summaryQuery,
      hasResult: summarySnapshot !== undefined,
      key: summaryOptions.queryKey,
      load: () => queryClient.fetchQuery({ ...summaryOptions, ...READ_NOW }),
    },
    {
      label: '链路资源',
      query: costQuery,
      hasResult: costSnapshot !== undefined,
      key: costOptions.queryKey,
      load: () => queryClient.fetchQuery({ ...costOptions, ...READ_NOW }),
    },
    {
      label: '聊天配额',
      query: chatQuotaQuery,
      hasResult: chatQuotaQuery.data !== undefined,
      key: chatQuotaOptions.queryKey,
      load: () => queryClient.fetchQuery({ ...chatQuotaOptions, ...READ_NOW }),
    },
    {
      label: '租户资源配额',
      query: tenantQuotaQuery,
      hasResult: tenantQuotaQuery.data !== undefined,
      key: tenantQuotaOptions.queryKey,
      load: () => queryClient.fetchQuery({ ...tenantQuotaOptions, ...READ_NOW }),
    },
    {
      label: '数据集名称',
      query: labelsQuery,
      hasResult: labelsQuery.data !== undefined,
      key: datasetOptions.queryKey,
      load: () => queryClient.fetchQuery({ ...datasetOptions, ...READ_NOW }),
    },
  ]
  const errors = reads.filter((read) => read.query.isError)
  const [quotaOpen, setQuotaOpen] = useState(false)
  const [refreshPending, setRefreshPending] = useState(false)
  const [copying, setCopying] = useState(false)
  const refreshingRef = useRef(false)
  const copyingRef = useRef(false)
  const ownerRef = useRef({ active: true })
  const copyVisitRef = useRef<object>({})
  useLayoutEffect(() => {
    const owner = { active: true }
    ownerRef.current = owner
    return () => {
      owner.active = false
    }
  }, [])
  useLayoutEffect(() => {
    copyVisitRef.current = {}
  }, [windowDays, view, quotaOpen, rawQuota])

  function isCurrentOwner(owner: { active: boolean }) {
    return owner.active && ownerRef.current === owner && getAuthSessionKey() === sessionKey
  }
  async function readNow(read: (typeof reads)[number]) {
    const owner = ownerRef.current
    if (!isCurrentOwner(owner)) return
    await queryClient.cancelQueries({ queryKey: read.key, exact: true })
    if (!isCurrentOwner(owner)) return
    return read.load()
  }
  function retryRead(read: (typeof reads)[number]) {
    return Promise.allSettled([readNow(read)])
  }
  async function refresh() {
    if (refreshingRef.current) return
    const owner = ownerRef.current
    if (!isCurrentOwner(owner)) return
    const location = window.location.search
    refreshingRef.current = true
    setRefreshPending(true)
    try {
      const results = await Promise.allSettled(reads.map(readNow))
      if (
        isCurrentOwner(owner) &&
        window.location.search === location &&
        results.every((result) => result.status === 'fulfilled')
      ) {
        toast.success('用量已刷新')
      }
    } finally {
      refreshingRef.current = false
      if (isCurrentOwner(owner)) setRefreshPending(false)
    }
  }
  async function copyQuota() {
    if (copyingRef.current || !hasQuotaData) return
    const owner = ownerRef.current
    const visit = copyVisitRef.current
    if (!isCurrentOwner(owner)) return
    copyingRef.current = true
    setCopying(true)
    try {
      await navigator.clipboard.writeText(rawQuota)
      if (isCurrentOwner(owner) && copyVisitRef.current === visit) toast.success('配额已复制')
    } catch (error) {
      if (isCurrentOwner(owner) && copyVisitRef.current === visit) toast.error(formatApiError(error, '复制配额失败'))
    } finally {
      copyingRef.current = false
      if (isCurrentOwner(owner)) setCopying(false)
    }
  }

  return {
    scope,
    summaryQuery,
    costQuery,
    summarySnapshot,
    costSnapshot,
    summary,
    cost,
    rows,
    attributionWindowDays,
    hasAttributionSnapshot: attributionSnapshot !== undefined,
    quotas,
    quotaPending,
    rawQuota,
    hasQuotaData,
    errors,
    quotaOpen,
    setQuotaOpen,
    copying,
    refresh,
    retryRead,
    copyQuota,
    refreshing: refreshPending || reads.some((read) => read.query.isFetching),
  }
}
