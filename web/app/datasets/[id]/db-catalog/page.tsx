'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, BarChart3, Database, Play, Search, Settings2, Table2 } from '@/components/icons'

import { AppFrame } from '@/components/app-frame'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { OperationalWorkspace, DirectoryWorkspace, WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Panel } from '@/components/ui/panel'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useRouter } from '@/i18n/navigation'
import { formatApiError } from '@/lib/api-errors'
import { connectorApi, datasetApi } from '@/lib/api'
import { reportClientError } from '@/lib/client-logging'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

import type {
  ConnectorRunListResponse,
  ConnectorRunOut,
  Dataset,
  DbCatalogTableDetail,
  DbCatalogTableSummary,
  DbProfileSnapshot,
} from '@/types'

const ENGINE_OPTIONS: ReadonlyArray<'all' | 'mysql' | 'sqlserver'> = ['all', 'mysql', 'sqlserver']
const DB_CATALOG_LIST_LIMIT = 200
const dbCatalogPanelClass = ws.canvasPanel

type DbCatalogSyncConfig = {
  host: string
  port: number
  database: string
  username: string
  password: string
  max_tables: number
  profile_enabled: boolean
  include_tables: string[]
  include_schemas?: string[]
}

type SchemaColumnChange = {
  table?: unknown
  column?: unknown
  old?: Record<string, unknown>
  new?: Record<string, unknown>
}

function asDatasetId(raw: unknown): string | null {
  if (typeof raw === 'string' && raw.trim()) return raw
  if (Array.isArray(raw) && typeof raw[0] === 'string') return raw[0]
  return null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function stringItems(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function columnChangeItems(value: unknown): SchemaColumnChange[] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).map((item) => ({
    table: item.table,
    column: item.column,
    old: isRecord(item.old) ? item.old : {},
    new: isRecord(item.new) ? item.new : {},
  }))
}

function formatQualifiedName(t: DbCatalogTableSummary | DbCatalogTableDetail): string {
  const parts: string[] = []
  if (t.db_name) parts.push(t.db_name)
  if (t.schema_name) parts.push(t.schema_name)
  parts.push(t.table_name)
  return parts.filter(Boolean).join('.')
}

function parseNameList(raw: string, limit = 200): string[] {
  const parts = String(raw || '')
    .split(/[\n,]/g)
    .map((s) => s.trim())
    .filter(Boolean)
  const seen = new Set<string>()
  const out: string[] = []
  for (const p of parts) {
    if (seen.has(p)) continue
    seen.add(p)
    out.push(p)
    if (out.length >= limit) break
  }
  return out
}

export default function DatasetDbCatalogPage() {
  const queryClient = useQueryClient()
  const router = useRouter()
  const params = useParams()
  const datasetId = asDatasetId((params as Record<string, unknown>)?.id)

  const [pane, setPane] = useState<'directory' | 'detail'>('directory')
  const [engine, setEngine] = useState<'all' | 'mysql' | 'sqlserver'>('all')
  const [query, setQuery] = useState('')

  const [selectedId, setSelectedId] = useState<string | null>(null)

  const [syncOpen, setSyncOpen] = useState(false)
  const [syncConnectorId, setSyncConnectorId] = useState<'sqlserver_catalog' | 'mysql_catalog'>('sqlserver_catalog')
  const [syncHost, setSyncHost] = useState('')
  const [syncPort, setSyncPort] = useState<number>(1433)
  const [syncDatabase, setSyncDatabase] = useState('')
  const [syncUsername, setSyncUsername] = useState('')
  const [syncPassword, setSyncPassword] = useState('')
  const [syncIncludeSchemas, setSyncIncludeSchemas] = useState('')
  const [syncIncludeTables, setSyncIncludeTables] = useState('')
  const [syncMaxTables, setSyncMaxTables] = useState<number>(200)
  const [syncProfileEnabled, setSyncProfileEnabled] = useState(true)
  const [syncSubmitting, setSyncSubmitting] = useState(false)
  const [syncError, setSyncError] = useState<string | null>(null)

  const catalogListParams = useMemo(
    () => ({
      skip: 0,
      limit: DB_CATALOG_LIST_LIMIT,
      engine: engine === 'all' ? undefined : engine,
      q: query.trim() ? query.trim() : undefined,
    }),
    [engine, query]
  )
  const datasetQuery = useQuery({
    queryKey: queryKeys.datasets.detail(datasetId || ''),
    queryFn: () => {
      if (!datasetId) throw new Error('缺少数据集 ID')
      return datasetApi.get(datasetId)
    },
    enabled: Boolean(datasetId),
  })
  const catalogTablesQuery = useQuery({
    queryKey: queryKeys.datasets.dbCatalogTables(
      datasetId || '',
      catalogListParams
    ),
    queryFn: () => {
      if (!datasetId) throw new Error('缺少数据集 ID')
      return datasetApi.listDbCatalogTables(datasetId, catalogListParams)
    },
    enabled: Boolean(datasetId),
  })
  const latestRunQueryKey = queryKeys.connectors.runs({
    dataset_id: datasetId || '',
    limit: 10,
  })
  const latestRunQuery = useQuery({
    queryKey: latestRunQueryKey,
    queryFn: () => {
      if (!datasetId) throw new Error('缺少数据集 ID')
      return connectorApi.listRuns({ dataset_id: datasetId, limit: 10 })
    },
    enabled: Boolean(datasetId),
  })
  const dataset = (datasetQuery.data ?? null) as Dataset | null
  const items: DbCatalogTableSummary[] = useMemo(
    () => catalogTablesQuery.data?.items || [],
    [catalogTablesQuery.data?.items]
  )
  const latestRun = useMemo<ConnectorRunOut | null>(() => {
    const runs = latestRunQuery.data?.items || []
    const catalogRun = runs.find((run) =>
      ['mysql_catalog', 'sqlserver_catalog'].includes(
        String(run.connector_id || '').toLowerCase()
      )
    )
    return catalogRun || null
  }, [latestRunQuery.data?.items])
  const latestRunLoading = latestRunQuery.isFetching
  const isLoading = datasetQuery.isFetching || catalogTablesQuery.isFetching
  const loadError = datasetQuery.error ?? catalogTablesQuery.error
  const loadErrorUpdatedAt = Math.max(
    datasetQuery.errorUpdatedAt,
    catalogTablesQuery.errorUpdatedAt
  )
  const { refetch: refetchDataset } = datasetQuery
  const { refetch: refetchCatalogTables } = catalogTablesQuery
  const { refetch: refetchLatestRun } = latestRunQuery
  const refreshCatalogList = useCallback(() => {
    refetchDataset()
    refetchCatalogTables()
  }, [refetchCatalogTables, refetchDataset])
  const entitlementHash = useMemo(() => {
    const maybeHash = (latestRun?.stats as { result?: { entitlement_hash?: unknown } } | null | undefined)
      ?.result?.entitlement_hash
    return typeof maybeHash === 'string' ? maybeHash : undefined
  }, [latestRun])
  const detailQuery = useQuery({
    queryKey: queryKeys.datasets.dbCatalogTableDetail(
      datasetId || '',
      selectedId || ''
    ),
    queryFn: () => {
      if (!datasetId || !selectedId) throw new Error('缺少表 ID')
      return datasetApi.getDbCatalogTable(datasetId, selectedId)
    },
    enabled: Boolean(datasetId && selectedId),
  })
  const latestProfileQuery = useQuery({
    queryKey: queryKeys.datasets.dbCatalogProfiles(datasetId || '', {
      table_id: selectedId || '',
      entitlement_hash: entitlementHash,
      skip: 0,
      limit: 1,
    }),
    queryFn: () => {
      if (!datasetId || !selectedId) throw new Error('缺少表 ID')
      return datasetApi.listDbCatalogProfiles(datasetId, {
        table_id: selectedId,
        entitlement_hash: entitlementHash,
        skip: 0,
        limit: 1,
      })
    },
    enabled: Boolean(datasetId && selectedId),
  })
  const selected = selectedId ? detailQuery.data ?? null : null
  const latestProfile: DbProfileSnapshot | null =
    selectedId ? latestProfileQuery.data?.items?.[0] || null : null
  const detailLoading =
    Boolean(selectedId) &&
    (detailQuery.isFetching || latestProfileQuery.isFetching)

  useEffect(() => {
    setSyncPort(syncConnectorId === 'sqlserver_catalog' ? 1433 : 3306)
  }, [syncConnectorId])

  const submitSync = useCallback(async () => {
    if (!datasetId) return
    const host = syncHost.trim()
    const database = syncDatabase.trim()
    const username = syncUsername.trim()
    const password = syncPassword
    if (!host || !database || !username || !password) {
      setSyncError('host / database / username / password 为必填')
      return
    }

    const cfg: DbCatalogSyncConfig = {
      host,
      port: (() => {
    if (Number.isFinite(syncPort)) {
        return Math.trunc(syncPort);
    }
    else if (syncConnectorId === 'sqlserver_catalog') {
            return 1433;
        }
        else {
            return 3306;
        }
})(),
      database,
      username,
      password,
      max_tables: Number.isFinite(syncMaxTables) ? Math.trunc(syncMaxTables) : 200,
      profile_enabled: Boolean(syncProfileEnabled),
      include_tables: parseNameList(syncIncludeTables, 500),
    }
    if (syncConnectorId === 'sqlserver_catalog') {
      cfg.include_schemas = parseNameList(syncIncludeSchemas, 200)
    }

    setSyncSubmitting(true)
    setSyncError(null)
    try {
      const run = await connectorApi.createRun({
        connector_id: syncConnectorId,
      dataset_id: datasetId,
      config: cfg,
      })
      queryClient.setQueryData<ConnectorRunListResponse | undefined>(
        latestRunQueryKey,
        (current) => {
          const items = current?.items || []
          const nextItems = [run, ...items.filter((item) => item.id !== run.id)]
            .slice(0, 10)
          return {
            total: Math.max(current?.total || 0, nextItems.length),
            items: nextItems,
          }
        }
      )
      toast.success(`已创建同步任务：${run.id.slice(0, 8)}`)
      setSyncOpen(false)
      setSyncPassword('')
      // Best-effort: refresh after a short delay (sync runs async).
      globalThis.window.setTimeout(() => {
        refreshCatalogList()
        refetchLatestRun()
      }, 1500)
    } catch (e: unknown) {
      reportClientError('Failed to create DB catalog run', e)
      setSyncError(formatApiError(e, '创建同步任务失败'))
    } finally {
      setSyncSubmitting(false)
    }
  }, [
    datasetId,
    refreshCatalogList,
    syncConnectorId,
    syncDatabase,
    syncHost,
    syncIncludeSchemas,
    syncIncludeTables,
    syncMaxTables,
    syncPassword,
    syncPort,
    syncProfileEnabled,
    syncUsername,
    latestRunQueryKey,
    queryClient,
    refetchLatestRun,
  ])

  useEffect(() => {
    if (!loadError) return
    toast.error(formatApiError(loadError, '加载数据库目录失败'))
  }, [loadError, loadErrorUpdatedAt])

  useEffect(() => {
    if (!detailQuery.error) return
    reportClientError('Failed to load DB catalog table detail', detailQuery.error)
    toast.error(formatApiError(detailQuery.error, '加载表结构失败'))
  }, [detailQuery.error, detailQuery.errorUpdatedAt])

  useEffect(() => {
    setSelectedId((prev) => {
      if (prev && items.some((t) => t.id === prev)) return prev
      return items[0]?.id || null
    })
  }, [items])

  const selectedSummary = useMemo(() => {
    if (!selected) return null
    const name = formatQualifiedName(selected)
    const rowCount = (() => {
      const v = latestProfile?.profile?.row_count_estimate
      if (v === null || v === undefined) return null
      if (typeof v === 'number' && Number.isFinite(v)) return v
      const n = typeof v === 'string' ? Number.parseInt(v, 10) : Number.NaN
      return Number.isFinite(n) ? n : null
    })()
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="outline" className="font-mono">
          {name}
        </Badge>
        <Badge variant="soft" className="font-mono">
          {selected.engine}
        </Badge>
        <Badge variant="soft" className="font-mono">
          {selected.table_type}
        </Badge>
        {rowCount === null ? null : (
          <Badge variant="soft" className="font-mono tabular-nums">
            rows~: {rowCount.toLocaleString()}
          </Badge>
        )}
        {selected.columns?.length ? (
          <Badge variant="soft" className="font-mono tabular-nums">
            cols: {selected.columns.length}
          </Badge>
        ) : null}
      </div>
    )
  }, [latestProfile, selected])
  const datasetName = dataset?.name || datasetId || '未选择数据集'
  const catalogTotal = catalogTablesQuery.data?.total ?? items.length
  const engineSummary = engine === 'all' ? '全部引擎' : engine
  const latestRunSummary = useMemo(() => {
    if (!latestRun) {
      return {
        status: '暂无同步',
        connector: '—',
        runId: '—',
        tables: 0,
        columns: 0,
        profiles: 0,
        freshness: null as string | null,
        diffTotal: 0,
        ta: 0,
        tr: 0,
        ca: 0,
        cr: 0,
        cc: 0,
        taItems: [] as string[],
        trItems: [] as string[],
        caItems: [] as string[],
        crItems: [] as string[],
        ccItems: [] as SchemaColumnChange[],
      }
    }

    const stats = isRecord(latestRun.stats) ? latestRun.stats : {}
    const result = isRecord(stats.result) ? stats.result : {}
    const schemaDoc = isRecord(stats.schema_doc) ? stats.schema_doc : {}
    const diff = isRecord(schemaDoc.schema_diff) ? schemaDoc.schema_diff : {}
    const ageSecRaw = schemaDoc.catalog_age_sec
    const ageSec = typeof ageSecRaw === 'number' && Number.isFinite(ageSecRaw) ? ageSecRaw : null
    const freshness =
      (() => {
        if (ageSec === null) return null
        if (ageSec < 90) return `${Math.round(ageSec)}s`
        if (ageSec < 3600) return `${Math.round(ageSec / 60)}m`
        return `${Math.round(ageSec / 3600)}h`
      })()
    const tables = Number(result.tables ?? schemaDoc.tables ?? 0)
    const columns = Number(result.columns_upserted ?? schemaDoc.columns ?? 0)
    const profiles = Number(result.profiles_written ?? schemaDoc.tables_with_profiles ?? 0)
    const tablesAdded = isRecord(diff.tables_added) ? diff.tables_added : {}
    const tablesRemoved = isRecord(diff.tables_removed) ? diff.tables_removed : {}
    const columnsAdded = isRecord(diff.columns_added) ? diff.columns_added : {}
    const columnsRemoved = isRecord(diff.columns_removed) ? diff.columns_removed : {}
    const columnsChanged = isRecord(diff.columns_changed) ? diff.columns_changed : {}
    const ta = Number(tablesAdded.count ?? 0)
    const tr = Number(tablesRemoved.count ?? 0)
    const ca = Number(columnsAdded.count ?? 0)
    const cr = Number(columnsRemoved.count ?? 0)
    const cc = Number(columnsChanged.count ?? 0)

    return {
      status: String(latestRun.status || 'unknown'),
      connector: String(latestRun.connector_id || 'connector'),
      runId: latestRun.id.slice(0, 8),
      tables: Number.isFinite(tables) ? tables : 0,
      columns: Number.isFinite(columns) ? columns : 0,
      profiles: Number.isFinite(profiles) ? profiles : 0,
      freshness,
      diffTotal: ta + tr + ca + cr + cc,
      ta,
      tr,
      ca,
      cr,
      cc,
      taItems: stringItems(tablesAdded.items),
      trItems: stringItems(tablesRemoved.items),
      caItems: stringItems(columnsAdded.items),
      crItems: stringItems(columnsRemoved.items),
      ccItems: columnChangeItems(columnsChanged.items),
    }
  }, [latestRun])

  return <AppFrame><OperationalWorkspace title="数据库目录" icon="dataset" mode="canvas" context={dataset?.name ?? '正在读取数据集…'} back={() => router.push('/datasets')} actions={<Button disabled={syncSubmitting} onClick={() => { setSyncError(null); setSyncOpen(true) }}><Play />新建同步</Button>}>
    {loadError ? <div className="px-5"><WorkspaceNotice retry={refreshCatalogList} pending={isLoading}>{formatApiError(loadError, '数据库目录读取失败')}</WorkspaceNotice></div> : null}
    <DirectoryWorkspace pane={pane} onPaneChange={setPane} directoryLabel="表目录" detailLabel="表详情" directory={<Panel variant="seamless" className={cn(dbCatalogPanelClass, 'flex min-h-0 flex-col p-0')}>
            <div className="shrink-0 border-b border-border/60 bg-card/65 p-3.5 dark:border-border/60 dark:bg-muted/20">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-foreground dark:text-foreground">表资产</div>
                  <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                    当前最多展示 {DB_CATALOG_LIST_LIMIT} 张表；按名称、schema 或引擎快速过滤。
                  </div>
                </div>
                <Badge variant="outline" className="shrink-0 rounded-lg font-mono text-[11px]">
                  {items.length}/{catalogTotal}
                </Badge>
              </div>
              <div className="mt-3 flex items-center gap-2 rounded-xl border border-border/60 bg-card/75 px-3 py-2 shadow-inner dark:border-border/60 dark:bg-muted/20">
                <Search className="size-3.5 shrink-0 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="db / schema / table"
                  className="focus-ring h-7 border-0 bg-transparent px-0 text-[13px] shadow-none"
                />
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {ENGINE_OPTIONS.map((k) => (
                  <Button
                    key={k}
                    type="button"
                    variant={engine === k ? 'secondary' : 'outline'}
                    size="sm"
                    className={ws.filterButton}
                    data-selected={engine === k}
                    aria-pressed={engine === k}
                    onClick={() => setEngine(k)}
                  >
                    {k === 'all' ? '全部' : k === 'sqlserver' ? 'SQL Server' : 'MySQL'}
                  </Button>
                ))}
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-3 no-scrollbar">
              {(() => {
                if (isLoading) {
                  return (
                    <div className="space-y-2">
                      <Skeleton className="h-12 w-full rounded-xl" />
                      <Skeleton className="h-12 w-full rounded-xl" />
                      <Skeleton className="h-12 w-full rounded-xl" />
                      <Skeleton className="h-12 w-full rounded-xl" />
                    </div>
                  )
                }
                if (loadError) return <p className="py-5 text-sm text-destructive">目录读取失败。</p>
                if (items.length) {
                  return (
                    <div className="space-y-1.5">
                      {items.map((t) => {
                        const active = t.id === selectedId
                        return (
                          <button
                            key={t.id}
                            type="button"
                            className={cn(
                              ws.directoryRow,
                              active
                                ? 'bg-primary/5'
                                : 'hover:bg-muted/40'
                            )}
                            onClick={() => { setSelectedId(t.id); setPane('detail') }}
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div className="min-w-0">
                                <div className="truncate font-mono text-xs tabular-nums text-foreground dark:text-foreground">{formatQualifiedName(t)}</div>
                                <div className="mt-1 truncate text-[11px] text-muted-foreground">{t.comment || '暂无备注'}</div>
                              </div>
                              <Badge variant="outline" className="shrink-0 rounded-lg font-mono text-[10px]">
                                {t.engine}
                              </Badge>
                            </div>
                          </button>
                        )
                      })}
                    </div>
                  )
                }
                return (
                  <div className="py-4">
                    <div className="text-sm font-semibold text-foreground">暂无数据库目录</div>
                    <div className="mt-1 text-xs leading-5 text-muted-foreground">
                      先运行 SQLServer/MySQL 目录同步。该流程只同步结构与安全统计，不读取原始行。
                    </div>
                  </div>
                )
              })()}
            </div>

            <div className="shrink-0 border-t border-border/60 bg-card/65 p-3 dark:border-border/60 dark:bg-muted/20">
              <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                <Badge variant="outline" className="rounded-lg font-mono text-[10px]">{latestRunSummary.connector}</Badge>
                <Badge variant="soft" className="rounded-lg font-mono text-[10px]">run {latestRunSummary.runId}</Badge>
                <Badge variant="soft" className="rounded-lg font-mono text-[10px]">tables {latestRunSummary.tables}</Badge>
                {latestRunSummary.freshness ? (
                  <Badge variant="soft" className="rounded-lg font-mono text-[10px]">fresh {latestRunSummary.freshness}</Badge>
                ) : null}
              </div>
              {latestRunSummary.diffTotal > 0 ? (
                <details className="mt-2 rounded-xl border border-border/60 bg-card/55 px-3 py-2 dark:border-border/60 dark:bg-muted/20">
                  <summary className="cursor-pointer select-none text-[11px] font-medium text-muted-foreground">
                    schema diff：+表 {latestRunSummary.ta} / -表 {latestRunSummary.tr} / +列 {latestRunSummary.ca} / -列 {latestRunSummary.cr} / 变更 {latestRunSummary.cc}
                  </summary>
                  <div className="mt-2 max-h-40 space-y-2 overflow-y-auto text-[11px] no-scrollbar">
                    {latestRunSummary.taItems.length ? (
                      <div>
                        <div className="font-semibold text-foreground">新增表</div>
                        <div className="mt-1 break-words font-mono text-muted-foreground">{latestRunSummary.taItems.join(', ')}</div>
                      </div>
                    ) : null}
                    {latestRunSummary.trItems.length ? (
                      <div>
                        <div className="font-semibold text-foreground">删除表</div>
                        <div className="mt-1 break-words font-mono text-muted-foreground">{latestRunSummary.trItems.join(', ')}</div>
                      </div>
                    ) : null}
                    {latestRunSummary.caItems.length ? (
                      <div>
                        <div className="font-semibold text-foreground">新增列</div>
                        <div className="mt-1 break-words font-mono text-muted-foreground">{latestRunSummary.caItems.join(', ')}</div>
                      </div>
                    ) : null}
                    {latestRunSummary.crItems.length ? (
                      <div>
                        <div className="font-semibold text-foreground">删除列</div>
                        <div className="mt-1 break-words font-mono text-muted-foreground">{latestRunSummary.crItems.join(', ')}</div>
                      </div>
                    ) : null}
                    {latestRunSummary.ccItems.length ? (
                      <div>
                        <div className="font-semibold text-foreground">变更列</div>
                        <div className="mt-1 space-y-1 font-mono text-muted-foreground">
                          {latestRunSummary.ccItems.slice(0, 20).map((it) => {
                            const key = `${toTrimmedPrimitiveString(it?.table)}.${toTrimmedPrimitiveString(it?.column)}`
                            return (
                              <div key={key} className="break-words">
                                {key} ({toTrimmedPrimitiveString(it?.old?.data_type)} → {toTrimmedPrimitiveString(it?.new?.data_type)})
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    ) : null}
                  </div>
                </details>
              ) : null}
            </div>
          </Panel>}><Tabs defaultValue="structure"><TabsList className={ws.tabList}><TabsTrigger value="structure">字段结构</TabsTrigger><TabsTrigger value="profile">安全画像</TabsTrigger><TabsTrigger value="history">同步记录</TabsTrigger></TabsList><TabsContent value="structure" className={ws.tabContent}>{detailQuery.isError ? <WorkspaceNotice retry={() => { void detailQuery.refetch() }}>{formatApiError(detailQuery.error, '表结构读取失败')}</WorkspaceNotice> : null}<Panel variant="seamless" className={cn(dbCatalogPanelClass, 'flex min-h-0 min-w-0 flex-col p-0')}>
            <div className="flex shrink-0 items-start justify-between gap-3 border-b border-border/60 bg-card/65 px-3.5 py-3 dark:border-border/60 dark:bg-muted/20">
              <div className="min-w-0 space-y-1.5">
                <div className="text-sm font-semibold text-foreground dark:text-foreground">表结构</div>
                {selectedSummary || <div className="text-xs text-muted-foreground"></div>}
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-3 no-scrollbar">
              {(() => {
                if (detailLoading) {
                  return (
                    <div className="space-y-2">
                      <Skeleton className="h-8 w-44 rounded-xl" />
                      <Skeleton className="h-11 w-full rounded-xl" />
                      <Skeleton className="h-11 w-full rounded-xl" />
                      <Skeleton className="h-11 w-full rounded-xl" />
                    </div>
                  )
                }
                if (selected) {
                  return (
                    <div className="overflow-hidden">
                      <div className="grid grid-cols-12 gap-0 bg-muted/40 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground dark:bg-muted/30">
                        <div className="col-span-5 px-3 py-2">字段</div>
                        <div className="col-span-4 px-3 py-2">类型</div>
                        <div className="col-span-3 px-3 py-2">允许为空</div>
                      </div>
                      {selected.columns?.length ? (
                        <div className="divide-y divide-border/60 dark:divide-border/60">
                          {selected.columns.map((c) => (
                            <div key={c.id} className="grid grid-cols-12 gap-0 text-xs hover:bg-info/5">
                              <div className="col-span-5 truncate px-3 py-2.5 font-mono text-foreground dark:text-foreground">{c.name}</div>
                              <div className="col-span-4 truncate px-3 py-2.5 font-mono text-muted-foreground">{c.data_type || '—'}</div>
                              <div className="col-span-3 px-3 py-2.5 font-mono text-muted-foreground">
                                {(() => {
                                  if (c.nullable === null || c.nullable === undefined) return '—'
                                  return c.nullable ? 'true' : 'false'
                                })()}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="p-5 text-sm text-muted-foreground">暂无列信息，可能尚未完成同步。</div>
                      )}
                    </div>
                  )
                }
                return (
                  <div className={ws.empty}><h2>{items.length ? '选择数据库表' : query || engine !== 'all' ? '没有匹配的表' : '尚未同步数据库目录'}</h2><p>{items.length ? '从目录选择一张表，查看字段与安全画像。' : query || engine !== 'all' ? '调整搜索或引擎筛选后重试。' : '建立数据库连接后，同步表结构与安全统计。'}</p>{!items.length && !loadError ? <Button variant="outline" onClick={() => { if (query || engine !== 'all') { setQuery(''); setEngine('all') } else setSyncOpen(true) }}>{query || engine !== 'all' ? '清除筛选' : '新建同步'}</Button> : null}</div>
                )
              })()}
            </div>
          </Panel></TabsContent><TabsContent value="profile" className={ws.tabContent}><section className={ws.section}><h2 className={ws.sectionTitle}>最新安全画像</h2>{latestProfileQuery.isError ? <WorkspaceNotice retry={() => { void latestProfileQuery.refetch() }}>{formatApiError(latestProfileQuery.error, '安全画像读取失败')}</WorkspaceNotice> : latestProfile ? <><p className="my-3 text-xs text-muted-foreground">{latestProfile.created_at}</p><pre className="overflow-auto bg-muted/20 p-3 text-xs leading-6">{JSON.stringify(latestProfile.profile, null, 2)}</pre><details className="mt-4 text-sm"><summary>采样信息</summary><pre className="overflow-auto py-3 text-xs">{JSON.stringify(latestProfile.sample_meta, null, 2)}</pre></details></> : <p className="py-4 text-sm text-muted-foreground">{latestProfileQuery.isFetching ? '正在读取画像…' : '当前表没有安全画像记录。'}</p>}</section></TabsContent><TabsContent value="history" className={ws.tabContent}><section className={ws.section}><div className={ws.sectionHeading}><h2 className={ws.sectionTitle}>同步记录</h2><Button variant="ghost" onClick={() => { void latestRunQuery.refetch() }}>重新读取记录</Button></div>{latestRunQuery.isError ? <WorkspaceNotice>{formatApiError(latestRunQuery.error, '同步记录读取失败')}</WorkspaceNotice> : <div className={ws.tableScroll}><table className={ws.table} aria-label="数据库目录同步记录"><thead><tr><th>运行</th><th>连接器</th><th>状态</th><th>创建时间</th></tr></thead><tbody>{(latestRunQuery.data?.items ?? []).filter(run => ['mysql_catalog', 'sqlserver_catalog'].includes(run.connector_id)).map(run => <tr key={run.id}><td className="font-mono text-xs">{run.id.slice(0, 8)}</td><td>{run.connector_id}</td><td>{run.status}</td><td>{run.created_at}</td></tr>)}</tbody></table></div>}</section></TabsContent></Tabs></DirectoryWorkspace>
        <Dialog
          open={syncOpen}
          onOpenChange={(open) => {
            setSyncOpen(open)
            if (!open) setSyncError(null)
          }}
        >
          <DialogContent className={ws.dialog}>
            <DialogHeader className={ws.dialogHeader}>
              <DialogTitle>数据库目录同步</DialogTitle>
              <DialogDescription>
                仅同步结构与安全画像（聚合统计）；不读取原始行，不向大模型外发数据库行数据。
              </DialogDescription>
            </DialogHeader>

            <div className={ws.dialogBody}>
              <div className="space-y-2">
                <Label>连接器</Label>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant={syncConnectorId === 'sqlserver_catalog' ? 'secondary' : 'outline'}
                    size="sm"
                    className="font-mono"
                    onClick={() => setSyncConnectorId('sqlserver_catalog')}
                  >
                    sqlserver
                  </Button>
                  <Button
                    type="button"
                    variant={syncConnectorId === 'mysql_catalog' ? 'secondary' : 'outline'}
                    size="sm"
                    className="font-mono"
                    onClick={() => setSyncConnectorId('mysql_catalog')}
                  >
                    mysql
                  </Button>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="space-y-2 sm:col-span-2">
                  <Label>主机</Label>
                  <Input aria-label="主机" value={syncHost} onChange={(e) => setSyncHost(e.target.value)} placeholder="db.example.com" />
                </div>
                <div className="space-y-2">
                  <Label>端口</Label>
                  <Input
                    value={String(syncPort)}
                    onChange={(e) => setSyncPort(Number.parseInt(e.target.value || '0', 10) || 0)}
                    inputMode="numeric"
                    placeholder={syncConnectorId === 'sqlserver_catalog' ? '1433' : '3306'}
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label>数据库</Label>
                  <Input aria-label="数据库" value={syncDatabase} onChange={(e) => setSyncDatabase(e.target.value)} placeholder="demo" />
                </div>
                <div className="space-y-2">
                  <Label>用户名</Label>
                  <Input aria-label="用户名" value={syncUsername} onChange={(e) => setSyncUsername(e.target.value)} placeholder="svc_reader" />
                </div>
              </div>

              <div className="space-y-2">
                <Label>密码</Label>
                <Input
                  type="password" aria-label="密码"
                  value={syncPassword}
                  onChange={(e) => setSyncPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="new-password"
                />
              </div>

              {syncConnectorId === 'sqlserver_catalog' ? (
                <div className="space-y-2">
                  <Label>Schema 范围（选填）</Label>
                  <Textarea
                    value={syncIncludeSchemas}
                    onChange={(e) => setSyncIncludeSchemas(e.target.value)}
                    placeholder="dbo\nsales"
                    rows={2}
                  />
                </div>
              ) : null}

              <div className="space-y-2">
                <Label>同步表范围（选填）</Label>
                <Textarea
                  value={syncIncludeTables}
                  onChange={(e) => setSyncIncludeTables(e.target.value)}
                  placeholder={syncConnectorId === 'sqlserver_catalog' ? 'dbo.users\ndbo.orders' : 'users\norders'}
                  rows={3}
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label>最大表数</Label>
                  <Input
                    value={String(syncMaxTables)}
                    onChange={(e) => setSyncMaxTables(Number.parseInt(e.target.value || '0', 10) || 0)}
                    inputMode="numeric"
                    placeholder="200"
                  />
                </div>
                <div className="rounded-xl border border-border bg-muted/20 px-4 py-3 flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-medium">安全画像</div>
                    <div className="text-xs text-muted-foreground text-pretty truncate">
                      记录 row_count_estimate 等聚合统计
                    </div>
                  </div>
                  <Switch checked={syncProfileEnabled} onCheckedChange={setSyncProfileEnabled} aria-label="profile enabled" />
                </div>
              </div>

              {syncError ? <WorkspaceNotice>{syncError}</WorkspaceNotice> : null}
            </div>

            <DialogFooter className={ws.dialogFooter}>
              <Button variant="outline" onClick={() => setSyncOpen(false)} disabled={syncSubmitting}>
                取消
              </Button>
              <Button onClick={submitSync} disabled={syncSubmitting}>
                <Play className="h-4 w-4" />
                {syncSubmitting ? '正在创建...' : '开始同步'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
</OperationalWorkspace></AppFrame>
}
