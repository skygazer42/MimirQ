'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useTenantAccess } from '@/hooks/use-tenant-access'
import { auditApi } from '@/lib/api/audit'
import { queryKeys } from '@/lib/query-keys'
import { TENANT_PERMISSIONS, tenantAccessAllows } from '@/lib/tenant-permissions'
import type { AuditLogItem } from '@/types'
import { cleanFilters, emptyFilters, formatAuditError, parseAuditLocation, persistScope, pretty, validateFilters, type AuditFilters, type AuditScope } from './audit-model'

export type ToolKind = 'export' | 'purge' | null
const EMPTY_ROWS: AuditLogItem[] = []
export function useAudit() {
  const [scope, setScope] = useState(() => parseAuditLocation(typeof window === 'undefined' ? '' : window.location.search))
  const [selected, setSelected] = useState<string[]>([])
  const [record, setRecord] = useState<AuditLogItem | null>(null)
  const [rawOpen, setRawOpen] = useState(false)
  const [tool, setTool] = useState<ToolKind>(null)
  const [toolFilters, setToolFilters] = useState<AuditFilters>(emptyFilters)
  const [deleteTarget, setDeleteTarget] = useState<string[] | null>(null)
  const [deleteError, setDeleteError] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const lock = useRef(false), opener = useRef<HTMLElement | null>(null), recordOpener = useRef<HTMLElement | null>(null), deleteOpener = useRef<HTMLElement | null>(null)
  const access = useTenantAccess(), queryClient = useQueryClient()
  const canManage = tenantAccessAllows(access.data, TENANT_PERMISSIONS.AUDIT_MANAGE)
  const filters = useMemo(() => cleanFilters(scope.filters), [scope.filters])
  const filterError = validateFilters(filters)
  const queryParams = useMemo(() => ({ ...filters, skip: (scope.page - 1) * scope.limit, limit: scope.limit }), [filters, scope.page, scope.limit])
  const logs = useQuery({ queryKey: queryKeys.audit.logs(queryParams), queryFn: () => auditApi.listLogs(queryParams), enabled: !filterError })
  const options = useQuery({
    queryKey: queryKeys.audit.filterOptions,
    queryFn: async () => {
      const first = await auditApi.listLogs({ skip: 0, limit: 200 })
      const pages = Math.min(5, Math.ceil(first.total / 200))
      const more = await Promise.all(Array.from({ length: Math.max(0, pages - 1) }, (_, i) => auditApi.listLogs({ skip: (i + 1) * 200, limit: 200 })))
      return [...first.items, ...more.flatMap(p => p.items)]
    }, staleTime: 300_000,
  })
  const rows = logs.data?.items ?? EMPTY_ROWS
  const total = logs.data?.total ?? null
  const pageCount = Math.max(1, Math.ceil((total ?? 0) / scope.limit))
  const selectedSet = useMemo(() => new Set(selected), [selected])
  const selectedVisible = rows.filter(row => selectedSet.has(row.id)).length
  const optionValues = useMemo(() => {
    const all = [...(options.data ?? []), ...rows]
    return Object.fromEntries((['action', 'actor_id', 'resource_type'] as const).map(key => [key, [...new Set([...all.map(row => row[key]), scope.filters[key]].filter((v): v is string => typeof v === 'string' && Boolean(v.trim())))].sort()])) as Record<'action' | 'actor_id' | 'resource_type', string[]>
  }, [options.data, rows, scope.filters])

  useEffect(() => {
    const restore = () => { setScope(parseAuditLocation(window.location.search)); setSelected([]); setRecord(null) }
    window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [])
  useEffect(() => { if (!canManage) setSelected([]) }, [canManage])
  useEffect(() => {
    if (logs.isSuccess && scope.page > pageCount) {
      const next = { ...scope, page: pageCount }
      setScope(next); persistScope(next)
    }
  }, [logs.isSuccess, pageCount, scope])

  function update(next: Partial<AuditScope>) {
    const value = { ...scope, ...next }
    if (next.filters || next.limit !== undefined) { value.page = 1; setSelected([]) }
    setScope(value); persistScope(value)
  }
  function setFilters(next: AuditFilters) { update({ filters: { ...emptyFilters(), ...cleanFilters(next) } }) }
  function toggle(id: string, checked: boolean) { setSelected(current => checked ? [...new Set([...current, id])] : current.filter(value => value !== id)) }
  function togglePage(checked: boolean) {
    const ids = new Set(rows.map(row => row.id))
    setSelected(current => checked ? [...new Set([...current, ...ids])] : current.filter(id => !ids.has(id)))
  }
  function focus(element: HTMLElement | null, event: Event) {
    event.preventDefault()
    requestAnimationFrame(() => { if (element?.isConnected && element.getClientRects().length) element.focus(); else document.querySelector<HTMLElement>('[data-audit-records-heading]')?.focus() })
  }
  function openRecord(row: AuditLogItem, element: HTMLElement) { recordOpener.current = element; setRecord(row) }
  function openTool(kind: Exclude<ToolKind, null>, element: HTMLElement) { opener.current = element; setToolFilters({ ...scope.filters }); setTool(kind) }
  function openRaw(element: HTMLElement) { opener.current = element; setRawOpen(true) }
  function askDelete(ids: string[], element: HTMLElement | null) {
    if (!canManage || busy || !ids.length) return
    deleteOpener.current = element; setDeleteError(''); setDeleteTarget([...ids])
  }
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); toast.success('已复制') }
    catch { toast.error('复制失败，请重试') }
  }
  async function exclusive<T>(key: string, action: () => Promise<T>): Promise<T> {
    if (lock.current) throw new Error('请等待当前操作完成')
    lock.current = true; setBusy(key)
    try { return await action() } finally { lock.current = false; setBusy(null) }
  }
  async function refresh() { await Promise.all([logs.refetch({ cancelRefetch: false }), options.refetch({ cancelRefetch: false })]) }
  async function afterMutation() { await queryClient.invalidateQueries({ queryKey: ['audit'] }) }
  async function deleteRecords() {
    const ids = deleteTarget ? [...deleteTarget] : []
    if (!canManage || !ids.length || lock.current) return
    setDeleteError('')
    try {
      const result = await exclusive('delete', () => ids.length === 1 ? auditApi.deleteLog(ids[0]) : auditApi.bulkDeleteLogs(ids))
      const deleted = new Set(ids)
      setSelected(current => current.filter(id => !deleted.has(id)))
      setRecord(current => current && deleted.has(current.id) ? null : current)
      setDeleteTarget(null)
      toast.success(`已删除 ${result.deleted} 条${result.missing ? `，${result.missing} 条已不存在` : ''}`)
      await afterMutation()
    } catch (error) {
      setDeleteError(await formatAuditError(error, '删除未完成，选择已保留'))
      await afterMutation()
    }
  }

  return { scope, filters, filterError, logs, options, optionValues, rows, total, pageCount, canManage,
    selected, selectedSet, selectedVisible, setSelected, toggle, togglePage, update, setFilters,
    record, setRecord, openRecord, rawOpen, setRawOpen, openRaw, tool, setTool, toolFilters, openTool,
    busy, exclusive, afterMutation, refresh, copy, pretty,
    deleteTarget, setDeleteTarget, deleteError, askDelete, deleteRecords,
    restoreOpener: (event: Event) => focus(opener.current, event),
    restoreRecordOpener: (event: Event) => focus(recordOpener.current, event),
    restoreDeleteOpener: (event: Event) => focus(deleteOpener.current, event),
  }
}
export type AuditController = ReturnType<typeof useAudit>
