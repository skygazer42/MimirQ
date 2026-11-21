'use client'

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { useTenantAccess } from '@/hooks/use-tenant-access'
import { auditApi, type AuditLogDeleteResponse } from '@/lib/api/audit'
import { getAuthSessionKey } from '@/lib/auth-storage'
import { TENANT_PERMISSIONS, tenantAccessAllows } from '@/lib/tenant-permissions'
import type { AuditLogFilters, AuditLogItem, AuditLogListResponse } from '@/types/audit'
import {
  getAuditQueryFilters,
  createAuditFilterDraft,
  formatAuditError,
  parseAuditLocation,
  buildAuditLocation,
  getAuditFilterError,
  type AuditFilters,
  type AuditScope,
} from './audit-model'

const AUDIT_SUGGESTION_PAGE_SIZE = 200
export const AUDIT_SUGGESTION_LIMIT = 1000
const AUDIT_DELETE_BATCH_SIZE = 500
const EMPTY_AUDIT_ROWS: AuditLogItem[] = []

function replaceAuditLocation(scope: AuditScope) {
  window.history.replaceState(null, '', buildAuditLocation(window.location.href, scope))
}

export type AuditTool = { kind: 'export' | 'purge'; filters: AuditFilters }
type AuditSnapshot = {
  scope: AuditScope
  params: AuditLogFilters & { skip: number; limit: number }
  data: AuditLogListResponse
}
type AuditOperation = { kind: 'delete' | 'export' | 'purge'; owner: { active: boolean }; controller: AbortController }

async function loadAuditSuggestions(signal: AbortSignal) {
  const first = await auditApi.listLogs({ skip: 0, limit: AUDIT_SUGGESTION_PAGE_SIZE }, { signal })
  const rows = [...first.items]
  const pages = Math.ceil(Math.min(first.total, AUDIT_SUGGESTION_LIMIT) / AUDIT_SUGGESTION_PAGE_SIZE)
  for (let page = 1; page < pages; page += 1) {
    const response = await auditApi.listLogs(
      { skip: page * AUDIT_SUGGESTION_PAGE_SIZE, limit: AUDIT_SUGGESTION_PAGE_SIZE },
      { signal },
    )
    rows.push(...response.items)
  }
  return rows
}

function getAuditPageParameters(scope: AuditScope) {
  return { ...getAuditQueryFilters(scope.filters), skip: (scope.page - 1) * scope.limit, limit: scope.limit }
}

async function loadAuditSnapshot(
  scope: AuditScope,
  params: AuditSnapshot['params'],
  signal: AbortSignal,
): Promise<AuditSnapshot> {
  const data = await auditApi.listLogs(params, { signal })
  return { scope, params, data }
}

function getAuditPageCount(snapshot: AuditSnapshot): number | undefined {
  const remaining = Math.max(0, snapshot.data.total - snapshot.params.skip)
  if (snapshot.data.items.length !== Math.min(snapshot.scope.limit, remaining)) return undefined
  return Math.ceil(snapshot.data.total / snapshot.scope.limit)
}

export function useAudit(sessionKey: string, focusRecordsHeading: () => void) {
  const searchParams = useSearchParams()
  const search = searchParams.toString()
  const scope = useMemo(() => parseAuditLocation(search), [search])
  const filters = useMemo(() => getAuditQueryFilters(scope.filters), [scope.filters])
  const filterError = getAuditFilterError(filters)
  const queryPrefix = ['audit', sessionKey] as const
  const queryClient = useQueryClient()
  const access = useTenantAccess()
  const canManage = tenantAccessAllows(access.data, TENANT_PERMISSIONS.AUDIT_MANAGE)

  const [selected, setSelected] = useState<string[]>([])
  const [record, setRecord] = useState<AuditLogItem | null>(null)
  const [rawResponse, setRawResponse] = useState<AuditSnapshot | null>(null)
  const [acceptedSnapshot, setAcceptedSnapshot] = useState<AuditSnapshot | undefined>()
  const [tool, setTool] = useState<AuditTool | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<string[] | null>(null)
  const [deleteError, setDeleteError] = useState<string | undefined>()
  const [deleteResult, setDeleteResult] = useState<AuditLogDeleteResponse | null>(null)
  const [busy, setBusy] = useState<AuditOperation['kind'] | null>(null)
  const ownerRef = useRef({ active: true })
  const operationRef = useRef<AuditOperation | null>(null)
  const opener = useRef<HTMLElement | null>(null)
  const recordOpener = useRef<HTMLElement | null>(null)
  const deleteOpener = useRef<HTMLElement | null>(null)
  const copyVisitRef = useRef<object>({})
  const selectionScope = JSON.stringify([filters, scope.limit])

  useLayoutEffect(() => {
    const owner = { active: true }
    ownerRef.current = owner
    return () => {
      owner.active = false
      const operation = operationRef.current
      operationRef.current = null
      operation?.controller.abort()
    }
  }, [])
  useLayoutEffect(() => {
    setSelected([])
  }, [selectionScope, canManage])
  useLayoutEffect(() => {
    setRecord(null)
    setRawResponse(null)
  }, [search])
  useLayoutEffect(() => {
    copyVisitRef.current = {}
  }, [search, record?.id, rawResponse, tool])

  const queryParams = useMemo(() => getAuditPageParameters(scope), [scope])
  const logs = useQuery({
    queryKey: [...queryPrefix, 'logs', queryParams],
    queryFn: ({ signal }) => loadAuditSnapshot(scope, queryParams, signal),
    enabled: filterError === undefined,
  })
  const suggestionQuery = useQuery({
    queryKey: [...queryPrefix, 'suggestions'],
    queryFn: ({ signal }) => loadAuditSuggestions(signal),
    staleTime: 300_000,
  })
  useLayoutEffect(() => {
    if (logs.data !== undefined) setAcceptedSnapshot(logs.data)
  }, [logs.data])
  const snapshot = logs.data === undefined ? acceptedSnapshot : logs.data
  const displayedFilters = snapshot === undefined ? undefined : getAuditQueryFilters(snapshot.params)
  const showingPrevious = snapshot !== undefined && JSON.stringify(snapshot.params) !== JSON.stringify(queryParams)
  const rows = snapshot?.data.items ?? EMPTY_AUDIT_ROWS
  const total = snapshot?.data.total
  const pageCount = snapshot === undefined ? undefined : getAuditPageCount(snapshot)
  const countChangedDuringRead = snapshot !== undefined && pageCount === undefined
  const selectedSet = useMemo(() => new Set(selected), [selected])
  const selectedVisible = rows.filter((row) => selectedSet.has(row.id)).length
  const filterSuggestions = useMemo(() => {
    const candidates = suggestionQuery.data === undefined ? rows : [...suggestionQuery.data, ...rows]
    const values = (key: 'action' | 'actor_id' | 'resource_type') =>
      [
        ...new Set(
          [...candidates.map((row) => row[key]), scope.filters[key]].filter(
            (value): value is string => typeof value === 'string' && value.trim().length > 0,
          ),
        ),
      ].sort()
    return { action: values('action'), actor_id: values('actor_id'), resource_type: values('resource_type') }
  }, [suggestionQuery.data, rows, scope.filters])
  const deletionConfirmed =
    deleteTarget !== null && deleteResult !== null && deleteTarget.every((id) => deleteResult.ids.includes(id))

  useEffect(() => {
    if (
      !logs.isSuccess ||
      showingPrevious ||
      pageCount === undefined ||
      new URLSearchParams(window.location.search).toString() !== search
    )
      return
    const lastPage = pageCount === 0 ? 1 : pageCount
    if (scope.page > lastPage) replaceAuditLocation({ ...scope, page: lastPage })
  }, [logs.isSuccess, showingPrevious, pageCount, scope, search])

  function restoreSnapshotScope() {
    if (snapshot !== undefined)
      replaceAuditLocation({
        ...snapshot.scope,
        filters: { ...createAuditFilterDraft(), ...getAuditQueryFilters(snapshot.params) },
      })
  }

  function setFilters(next: AuditFilters | ((current: AuditFilters) => AuditFilters)) {
    const current = parseAuditLocation(window.location.search)
    const nextFilters = typeof next === 'function' ? next(current.filters) : next
    replaceAuditLocation({ ...current, filters: nextFilters, page: 1 })
  }
  function changePage(offset: -1 | 1) {
    const current = parseAuditLocation(window.location.search)
    const page = current.page + offset
    if (page > 0) replaceAuditLocation({ ...current, page })
  }
  function setPageSize(limit: number) {
    const current = parseAuditLocation(window.location.search)
    replaceAuditLocation({ ...current, limit, page: 1 })
  }
  function toggle(id: string, checked: boolean) {
    setSelected((current) => (checked ? [...new Set([...current, id])] : current.filter((value) => value !== id)))
  }
  function togglePage(checked: boolean) {
    const ids = new Set(rows.map((row) => row.id))
    setSelected((current) => (checked ? [...new Set([...current, ...ids])] : current.filter((id) => !ids.has(id))))
  }
  function isCurrentSession() {
    return sessionKey === getAuthSessionKey()
  }
  function beginOperation(kind: AuditOperation['kind']): AuditOperation | null {
    if (!isCurrentSession() || operationRef.current !== null) return null
    const operation: AuditOperation = { kind, owner: ownerRef.current, controller: new AbortController() }
    operationRef.current = operation
    setBusy(kind)
    return operation
  }
  function isCurrentOperation(operation: AuditOperation) {
    return operationRef.current === operation && operation.owner.active && isCurrentSession()
  }
  function finishOperation(operation: AuditOperation) {
    operation.controller.abort()
    if (operationRef.current === operation) {
      operationRef.current = null
      if (operation.owner.active && isCurrentSession()) setBusy(null)
    }
  }
  function focus(element: HTMLElement | null, event: Event) {
    event.preventDefault()
    const owner = ownerRef.current
    requestAnimationFrame(() => {
      if (!owner.active || !isCurrentSession()) return
      if (element?.isConnected && element.getClientRects().length > 0) element.focus()
      else focusRecordsHeading()
    })
  }
  function openRecord(row: AuditLogItem, element: HTMLElement) {
    recordOpener.current = element
    setRecord(row)
  }
  function openTool(kind: AuditTool['kind'], element: HTMLElement) {
    if (operationRef.current !== null) return
    opener.current = element
    setTool({ kind, filters: { ...createAuditFilterDraft(), ...getAuditQueryFilters(scope.filters) } })
  }
  function closeTool() {
    if (operationRef.current === null) setTool(null)
  }
  function openRaw(element: HTMLElement) {
    if (snapshot === undefined) return
    opener.current = element
    setRawResponse(snapshot)
  }
  function askDelete(ids: string[], element: HTMLElement | null) {
    if (!canManage || showingPrevious || operationRef.current !== null || ids.length === 0) return
    deleteOpener.current = element
    setDeleteError(undefined)
    setDeleteResult(null)
    setDeleteTarget([...new Set(ids)])
  }
  function closeDelete() {
    if (operationRef.current === null) setDeleteTarget(null)
  }
  async function copy(text: string) {
    const owner = ownerRef.current
    const visit = copyVisitRef.current
    const isCurrent = () => owner.active && isCurrentSession() && copyVisitRef.current === visit
    try {
      await navigator.clipboard.writeText(text)
      if (isCurrent()) toast.success('已复制')
    } catch (error) {
      const message = await formatAuditError(error, '复制失败，请重试')
      if (isCurrent()) toast.error(message)
    }
  }
  async function refresh() {
    const requests: Promise<unknown>[] = [suggestionQuery.refetch({ cancelRefetch: false })]
    if (filterError === undefined) requests.push(logs.refetch({ cancelRefetch: false }))
    await Promise.all(requests)
  }
  async function afterMutation(): Promise<boolean> {
    if (!isCurrentSession()) return false
    const owner = ownerRef.current
    await queryClient.invalidateQueries({ queryKey: [...queryPrefix, 'logs'], refetchType: 'none' })
    const suggestions = queryClient.invalidateQueries({ queryKey: [...queryPrefix, 'suggestions'] })
    while (isCurrentSession() && owner.active) {
      const current = parseAuditLocation(window.location.search)
      const params = getAuditPageParameters(current)
      const filterError = getAuditFilterError(params)
      if (filterError !== undefined) {
        await suggestions
        throw new Error(filterError)
      }
      const queryKey = [...queryPrefix, 'logs', params] as const
      await queryClient.cancelQueries({ queryKey, exact: true })
      if (!isCurrentSession() || !owner.active) return false
      await queryClient.invalidateQueries({ queryKey, exact: true, refetchType: 'none' })
      if (!isCurrentSession() || !owner.active) return false
      const refreshed = await queryClient.fetchQuery({
        queryKey,
        queryFn: ({ signal }) => loadAuditSnapshot(current, params, signal),
        staleTime: 0,
        retry: false,
        networkMode: 'always',
      })
      if (!isCurrentSession() || !owner.active) return false
      const latest = getAuditPageParameters(parseAuditLocation(window.location.search))
      if (JSON.stringify(latest) !== JSON.stringify(params)) continue
      const refreshedPageCount = getAuditPageCount(refreshed)
      const lastPage = refreshedPageCount === 0 ? 1 : refreshedPageCount
      if (lastPage !== undefined && current.page > lastPage) {
        replaceAuditLocation({ ...current, page: lastPage })
        continue
      }
      await suggestions
      const visible = getAuditPageParameters(parseAuditLocation(window.location.search))
      if (JSON.stringify(visible) === JSON.stringify(params)) return true
    }
    await suggestions
    return false
  }
  async function retryDeleteRefresh() {
    if (!deletionConfirmed) return
    const operation = beginOperation('delete')
    if (operation === null) return
    setDeleteError(undefined)
    try {
      await afterMutation()
      if (isCurrentOperation(operation)) setDeleteTarget(null)
    } catch (error) {
      const message = await formatAuditError(error, '删除已确认，列表刷新失败')
      if (isCurrentOperation(operation)) setDeleteError(message)
    } finally {
      finishOperation(operation)
    }
  }
  async function deleteRecords() {
    if (!canManage || deleteTarget === null || deleteTarget.length === 0 || deletionConfirmed) return
    const operation = beginOperation('delete')
    if (operation === null) return
    const ids = [...deleteTarget]
    const confirmed = new Set<string>()
    let receipt: AuditLogDeleteResponse | null = null
    let failure: { error: unknown } | null = null
    let refreshFailure: { error: unknown } | null = null
    setDeleteError(undefined)
    setDeleteResult(null)
    try {
      try {
        for (let index = 0; index < ids.length; index += AUDIT_DELETE_BATCH_SIZE) {
          if (!isCurrentOperation(operation)) break
          const batch = ids.slice(index, index + AUDIT_DELETE_BATCH_SIZE)
          const response = ids.length === 1 ? await auditApi.deleteLog(batch[0]) : await auditApi.bulkDeleteLogs(batch)
          if (!isCurrentSession()) return
          for (const id of response.ids) confirmed.add(id)
          receipt =
            receipt === null
              ? response
              : {
                  requested: receipt.requested + response.requested,
                  deleted: receipt.deleted + response.deleted,
                  missing: receipt.missing + response.missing,
                  ids: [...receipt.ids, ...response.ids],
                }
          if (isCurrentOperation(operation)) {
            setDeleteResult(receipt)
            setSelected((current) => current.filter((id) => !confirmed.has(id)))
            setRecord((current) => (current !== null && confirmed.has(current.id) ? null : current))
          }
        }
      } catch (error) {
        failure = { error }
      }
      try {
        await afterMutation()
      } catch (error) {
        refreshFailure = { error }
      }
      if (!isCurrentOperation(operation)) return
      if (confirmed.size === ids.length && refreshFailure === null) {
        setDeleteTarget(null)
        if (receipt !== null) toast.success(`已删除 ${receipt.deleted} 条，${receipt.missing} 条原已不存在`)
        return
      }
      if (confirmed.size < ids.length) setDeleteTarget(ids.filter((id) => !confirmed.has(id)))
      const message =
        failure !== null
          ? await formatAuditError(failure.error, '部分日志的删除结果未确认，未确认项已保留')
          : refreshFailure !== null
            ? await formatAuditError(refreshFailure.error, '删除已确认，列表刷新失败')
            : '未确认的日志已保留'
      if (isCurrentOperation(operation)) setDeleteError(message)
    } finally {
      finishOperation(operation)
    }
  }

  return {
    scope,
    filters,
    filterError,
    logs,
    suggestionQuery,
    filterSuggestions,
    rows,
    total,
    pageCount,
    snapshot,
    displayedFilters,
    showingPrevious,
    countChangedDuringRead,
    restoreSnapshotScope,
    canManage,
    selected,
    selectedSet,
    selectedVisible,
    setSelected,
    toggle,
    togglePage,
    setFilters,
    changePage,
    setPageSize,
    record,
    setRecord,
    openRecord,
    rawResponse,
    setRawResponse,
    openRaw,
    tool,
    openTool,
    closeTool,
    busy,
    beginOperation,
    isCurrentOperation,
    isCurrentSession,
    finishOperation,
    afterMutation,
    refresh,
    copy,
    deleteTarget,
    deleteError,
    deleteResult,
    deletionConfirmed,
    askDelete,
    closeDelete,
    deleteRecords,
    retryDeleteRefresh,
    restoreOpener: (event: Event) => focus(opener.current, event),
    restoreRecordOpener: (event: Event) => {
      if (deleteTarget !== null) event.preventDefault()
      else focus(recordOpener.current, event)
    },
    restoreDeleteOpener: (event: Event) => focus(deleteOpener.current, event),
  }
}

export type AuditState = Readonly<ReturnType<typeof useAudit>>
