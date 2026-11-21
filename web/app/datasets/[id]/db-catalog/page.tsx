'use client'

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type FormEvent,
} from 'react'
import { useParams } from 'next/navigation'
import { skipToken, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { z } from 'zod'
import { Play, Search } from '@/components/icons'

import { AppFrame } from '@/components/app-frame'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  OperationalWorkspace,
  DirectoryWorkspace,
  WorkspaceNotice,
  workspaceStyles as ws,
} from '@/components/ui/operational-workspace'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Panel } from '@/components/ui/panel'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useRouter } from '@/i18n/navigation'
import { formatApiError } from '@/lib/api-errors'
import { connectorApi, datasetApi } from '@/lib/api'
import { dateTimeSchema, integerSchema } from '@/lib/response-schema'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { reportClientError } from '@/lib/client-logging'
import { queryKeys } from '@/lib/query-keys'
import { cn, formatDate } from '@/lib/utils'

import type { ConnectorRunOut, DbCatalogTableSummary } from '@/types'

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

const columnMetadataSchema = z.object({ data_type: z.string().nullable(), nullable: z.boolean().nullable() })
const textChangesSchema = z.object({
  count: integerSchema.nonnegative(),
  items: z.array(z.string()),
  truncated: z.boolean(),
})
const catalogSchemaDiffSchema = z.object({
  tables_added: textChangesSchema,
  tables_removed: textChangesSchema,
  columns_added: textChangesSchema,
  columns_removed: textChangesSchema,
  columns_changed: textChangesSchema.extend({
    items: z.array(
      z.object({ table: z.string(), column: z.string(), old: columnMetadataSchema, new: columnMetadataSchema }),
    ),
  }),
})

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function formatColumnMetadata(column: z.infer<typeof columnMetadataSchema>): string {
  const dataType = column.data_type ?? '类型未记录'
  if (column.nullable === null) return dataType
  return `${dataType}，${column.nullable ? '可为空' : '不可为空'}`
}

function CatalogSchemaDiff({ value }: Readonly<{ value: unknown }>) {
  const parsedDiff = useMemo(() => catalogSchemaDiffSchema.safeParse(value), [value])
  if (value === undefined) return null
  if (!parsedDiff.success) return <p className="mt-2 text-xs text-muted-foreground">结构变更记录格式无效。</p>

  const diff = parsedDiff.data
  if (Object.values(diff).every((group) => group.count === 0)) return null

  const textChanges = [
    { label: '新增表', ...diff.tables_added },
    { label: '删除表', ...diff.tables_removed },
    { label: '新增列', ...diff.columns_added },
    { label: '删除列', ...diff.columns_removed },
  ]
  const columnChanges = diff.columns_changed

  return (
    <details className="mt-2 rounded-xl border border-border/60 bg-card/55 px-3 py-2 dark:border-border/60 dark:bg-muted/20">
      <summary className="cursor-pointer select-none text-[11px] font-medium text-muted-foreground">结构变更</summary>
      <div className="mt-2 max-h-40 space-y-2 overflow-y-auto text-[11px] no-scrollbar">
        {textChanges
          .filter((change) => change.count > 0)
          .map((change) => (
            <div key={change.label}>
              <div className="font-semibold text-foreground">
                {change.label} {change.count}
                {change.truncated && `（显示 ${change.items.length} 项）`}
              </div>
              <div className="mt-1 break-words font-mono text-muted-foreground">{change.items.join(', ')}</div>
            </div>
          ))}
        {columnChanges.count > 0 && (
          <div>
            <div className="font-semibold text-foreground">
              变更列 {columnChanges.count}
              {columnChanges.truncated && `（显示 ${columnChanges.items.length} 项）`}
            </div>
            <div className="mt-1 space-y-1 font-mono text-muted-foreground">
              {columnChanges.items.map((change) => (
                <div key={JSON.stringify([change.table, change.column])} className="break-words">
                  {change.table}.{change.column}（{formatColumnMetadata(change.old)} →{' '}
                  {formatColumnMetadata(change.new)}）
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </details>
  )
}

function formatQualifiedName(table: DbCatalogTableSummary): string {
  return [table.db_name, table.schema_name, table.table_name].filter(Boolean).join('.')
}

function parseNameList(draft: string): string[] {
  const names = draft
    .split(/[\n,]/)
    .map((name) => name.trim())
    .filter((name) => name !== '')
  return [...new Set(names)]
}

export default function DatasetDbCatalogPage() {
  const { id: datasetId } = useParams<{ id: string }>()
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return <DatasetDbCatalogWorkspace key={JSON.stringify([datasetId, sessionKey])} datasetId={datasetId} />
}

function DatasetDbCatalogWorkspace({ datasetId }: Readonly<{ datasetId: string }>) {
  const router = useRouter()

  const [pane, setPane] = useState<'directory' | 'detail'>('directory')
  const [engine, setEngine] = useState<'all' | 'mysql' | 'sqlserver'>('all')
  const [query, setQuery] = useState('')

  const [selectedTableId, setSelectedTableId] = useState<string | null>(null)

  const [syncOpen, setSyncOpen] = useState(false)
  const [syncConnectorId, setSyncConnectorId] = useState<'sqlserver_catalog' | 'mysql_catalog'>('sqlserver_catalog')
  const [syncHost, setSyncHost] = useState('')
  const [syncPort, setSyncPort] = useState('1433')
  const [syncDatabase, setSyncDatabase] = useState('')
  const [syncUsername, setSyncUsername] = useState('')
  const [syncPassword, setSyncPassword] = useState('')
  const [syncIncludeSchemas, setSyncIncludeSchemas] = useState('')
  const [syncIncludeTables, setSyncIncludeTables] = useState('')
  const [syncMaxTables, setSyncMaxTables] = useState('200')
  const [syncProfileEnabled, setSyncProfileEnabled] = useState(true)
  const [syncSubmitting, setSyncSubmitting] = useState(false)
  const [syncError, setSyncError] = useState<string | null>(null)
  const syncRequestRef = useRef<Promise<ConnectorRunOut> | null>(null)
  const syncRefreshTimerRef = useRef<number | undefined>(undefined)

  const searchTerm = query.trim()
  const hasCatalogFilters = searchTerm !== '' || engine !== 'all'
  const catalogListParams = {
    skip: 0,
    limit: DB_CATALOG_LIST_LIMIT,
    engine: engine === 'all' ? undefined : engine,
    q: searchTerm === '' ? undefined : searchTerm,
  }
  const datasetQuery = useQuery({
    queryKey: queryKeys.datasets.detail(datasetId),
    queryFn: ({ signal }) => datasetApi.get(datasetId, { signal }),
  })
  const catalogTablesQuery = useQuery({
    queryKey: queryKeys.datasets.dbCatalogTables(datasetId, catalogListParams),
    queryFn: ({ signal }) => datasetApi.listDbCatalogTables(datasetId, catalogListParams, { signal }),
  })
  const runListParams = { dataset_id: datasetId, limit: 10 }
  const latestRunQueryKey = queryKeys.connectors.runs(runListParams)
  const latestRunQuery = useQuery({
    queryKey: latestRunQueryKey,
    queryFn: ({ signal }) => connectorApi.listRuns(runListParams, { signal }),
  })
  const dataset = datasetQuery.data
  const items = catalogTablesQuery.data?.items ?? []
  const activeTableId = selectedTableId ?? items[0]?.id ?? null
  const catalogRuns = latestRunQuery.data?.items.filter(
    (run) => run.connector_id === 'mysql_catalog' || run.connector_id === 'sqlserver_catalog',
  )
  const latestRun = catalogRuns?.[0]
  const isLoading = datasetQuery.isFetching || catalogTablesQuery.isFetching
  const loadError = datasetQuery.error ?? catalogTablesQuery.error
  const loadErrorUpdatedAt = Math.max(datasetQuery.errorUpdatedAt, catalogTablesQuery.errorUpdatedAt)
  const { refetch: refetchDataset } = datasetQuery
  const { refetch: refetchCatalogTables } = catalogTablesQuery
  const { refetch: refetchLatestRun } = latestRunQuery
  const refreshCatalogList = useCallback(() => {
    void refetchDataset()
    void refetchCatalogTables()
  }, [refetchCatalogTables, refetchDataset])
  const detailQuery = useQuery({
    queryKey: queryKeys.datasets.dbCatalogTableDetail(datasetId, activeTableId),
    queryFn:
      activeTableId === null
        ? skipToken
        : ({ signal }) => datasetApi.getDbCatalogTable(datasetId, activeTableId, { signal }),
  })
  const profileParams = activeTableId === null ? undefined : { table_id: activeTableId, skip: 0, limit: 1 }
  const latestProfileQuery = useQuery({
    queryKey: queryKeys.datasets.dbCatalogProfiles(datasetId, profileParams),
    queryFn:
      profileParams === undefined
        ? skipToken
        : ({ signal }) => datasetApi.listDbCatalogProfiles(datasetId, profileParams, { signal }),
  })
  const selected = detailQuery.data ?? null
  const latestProfile = latestProfileQuery.data?.items[0] ?? null

  useLayoutEffect(() => {
    return () => {
      syncRequestRef.current = null
      window.clearTimeout(syncRefreshTimerRef.current)
    }
  }, [])

  function selectSyncConnector(connectorId: typeof syncConnectorId) {
    if (connectorId === syncConnectorId) return
    setSyncConnectorId(connectorId)
    setSyncPort(connectorId === 'sqlserver_catalog' ? '1433' : '3306')
  }

  async function submitSync(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (syncRequestRef.current !== null) return
    const host = syncHost.trim()
    const database = syncDatabase.trim()
    const username = syncUsername.trim()
    const password = syncPassword
    if (!host || !database || !username || !password) {
      setSyncError('host / database / username / password 为必填')
      return
    }

    const config: DbCatalogSyncConfig = {
      host,
      port: Number(syncPort),
      database,
      username,
      password,
      max_tables: Number(syncMaxTables),
      profile_enabled: syncProfileEnabled,
      include_tables: parseNameList(syncIncludeTables),
    }
    if (syncConnectorId === 'sqlserver_catalog') {
      config.include_schemas = parseNameList(syncIncludeSchemas)
    }

    const request = connectorApi.createRun({ connector_id: syncConnectorId, dataset_id: datasetId, config })
    syncRequestRef.current = request
    setSyncSubmitting(true)
    setSyncError(null)
    try {
      const run = await request
      if (syncRequestRef.current !== request) return
      toast.success(`已创建同步任务：${run.id.slice(0, 8)}`)
      setSyncOpen(false)
      setSyncPassword('')
      window.clearTimeout(syncRefreshTimerRef.current)
      syncRefreshTimerRef.current = window.setTimeout(() => {
        refreshCatalogList()
        void refetchLatestRun()
      }, 1500)
    } catch (error) {
      if (syncRequestRef.current !== request) return
      reportClientError('Failed to create DB catalog run', error)
      setSyncError(formatApiError(error, '创建同步任务失败'))
    } finally {
      if (syncRequestRef.current === request) {
        syncRequestRef.current = null
        setSyncSubmitting(false)
      }
    }
  }

  useEffect(() => {
    if (!loadError) return
    reportClientError('Failed to load DB catalog', loadError)
  }, [loadError, loadErrorUpdatedAt])

  useEffect(() => {
    if (!detailQuery.error) return
    reportClientError('Failed to load DB catalog table detail', detailQuery.error)
  }, [detailQuery.error, detailQuery.errorUpdatedAt])

  const selectedSummary = useMemo(() => {
    if (!selected) return null
    const name = formatQualifiedName(selected)
    const rowCount = latestProfile?.profile.row_count_estimate
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
        {typeof rowCount === 'number' && Number.isFinite(rowCount) ? (
          <Badge variant="soft" className="font-mono tabular-nums">
            rows~: {rowCount.toLocaleString()}
          </Badge>
        ) : null}
        {selected.columns.length > 0 ? (
          <Badge variant="soft" className="font-mono tabular-nums">
            cols: {selected.columns.length}
          </Badge>
        ) : null}
      </div>
    )
  }, [latestProfile, selected])
  const schemaDocument = latestRun?.stats?.schema_doc
  const catalogStats = isRecord(schemaDocument) ? schemaDocument : undefined
  const syncResult = latestRun?.stats?.result
  const tableCount = isRecord(syncResult) ? syncResult.tables : undefined
  const catalogLastSeenAt = dateTimeSchema.safeParse(catalogStats?.catalog_last_seen_at)

  return (
    <AppFrame>
      <OperationalWorkspace
        title="数据库目录"
        icon="dataset"
        mode="canvas"
        context={dataset?.name ?? (datasetQuery.isPending ? '正在读取数据集…' : datasetId)}
        back={() => router.push('/datasets')}
        actions={
          <Button
            disabled={syncSubmitting}
            onClick={() => {
              setSyncError(null)
              setSyncOpen(true)
            }}
          >
            <Play />
            新建同步
          </Button>
        }
      >
        {loadError ? (
          <div className="px-5">
            <WorkspaceNotice retry={refreshCatalogList} pending={isLoading}>
              {formatApiError(loadError, '数据库目录读取失败')}
            </WorkspaceNotice>
          </div>
        ) : null}
        <DirectoryWorkspace
          pane={pane}
          onPaneChange={setPane}
          directoryLabel="表目录"
          detailLabel="表详情"
          directory={
            <Panel variant="seamless" className={cn(dbCatalogPanelClass, 'flex min-h-0 flex-col p-0')}>
              <div className="shrink-0 border-b border-border/60 bg-card/65 p-3.5 dark:border-border/60 dark:bg-muted/20">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-foreground dark:text-foreground">表资产</div>
                    <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                      当前最多展示 {DB_CATALOG_LIST_LIMIT} 张表；按名称、schema 或引擎快速过滤。
                    </div>
                  </div>
                  {catalogTablesQuery.data !== undefined && (
                    <Badge variant="outline" className="shrink-0 rounded-lg font-mono text-[11px]">
                      {items.length}/{catalogTablesQuery.data.total}
                    </Badge>
                  )}
                </div>
                <div className="mt-3 flex items-center gap-2 rounded-xl border border-border/60 bg-card/75 px-3 py-2 shadow-inner dark:border-border/60 dark:bg-muted/20">
                  <Search className="size-3.5 shrink-0 text-muted-foreground" />
                  <Input
                    aria-label="搜索数据库表"
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
                  if (catalogTablesQuery.isPending) {
                    return (
                      <div className="space-y-2">
                        <Skeleton className="h-12 w-full rounded-xl" />
                        <Skeleton className="h-12 w-full rounded-xl" />
                        <Skeleton className="h-12 w-full rounded-xl" />
                        <Skeleton className="h-12 w-full rounded-xl" />
                      </div>
                    )
                  }
                  if (catalogTablesQuery.isError && catalogTablesQuery.data === undefined) return null
                  if (items.length) {
                    return (
                      <div className="space-y-1.5">
                        {items.map((t) => {
                          const active = t.id === activeTableId
                          return (
                            <button
                              key={t.id}
                              type="button"
                              className={cn(ws.directoryRow, active ? 'bg-primary/5' : 'hover:bg-muted/40')}
                              aria-current={active ? 'true' : undefined}
                              onClick={() => {
                                setSelectedTableId(t.id)
                                setPane('detail')
                              }}
                            >
                              <div className="flex items-center justify-between gap-3">
                                <div className="min-w-0">
                                  <div className="truncate font-mono text-xs tabular-nums text-foreground dark:text-foreground">
                                    {formatQualifiedName(t)}
                                  </div>
                                  <div className="mt-1 truncate text-[11px] text-muted-foreground">
                                    {t.comment || '暂无备注'}
                                  </div>
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
                      <div className="text-sm font-semibold text-foreground">
                        {hasCatalogFilters ? '没有匹配的表' : '暂无数据库目录'}
                      </div>
                      <div className="mt-1 text-xs leading-5 text-muted-foreground">
                        {hasCatalogFilters ? '调整搜索或引擎筛选后重试。' : '先运行 SQL Server 或 MySQL 目录同步。'}
                      </div>
                    </div>
                  )
                })()}
              </div>

              <div className="shrink-0 border-t border-border/60 bg-card/65 p-3 dark:border-border/60 dark:bg-muted/20">
                {latestRun === undefined ? (
                  <p className="text-xs text-muted-foreground">
                    {latestRunQuery.isPending
                      ? '正在读取同步记录…'
                      : latestRunQuery.isError
                        ? '同步记录读取失败。'
                        : '最近的运行中没有数据库目录同步记录。'}
                  </p>
                ) : (
                  <>
                    <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                      <Badge variant="outline" className="rounded-lg font-mono text-[10px]">
                        {latestRun.connector_id}
                      </Badge>
                      <Badge variant="soft" className="rounded-lg font-mono text-[10px]">
                        任务 {latestRun.id.slice(0, 8)}
                      </Badge>
                      {typeof tableCount === 'number' && Number.isInteger(tableCount) && tableCount >= 0 && (
                        <Badge variant="soft" className="rounded-lg font-mono text-[10px]">
                          本次同步 {tableCount} 张表
                        </Badge>
                      )}
                      {catalogLastSeenAt.success && (
                        <Badge variant="soft" className="rounded-lg text-[10px]">
                          目录更新于 <time dateTime={catalogLastSeenAt.data}>{formatDate(catalogLastSeenAt.data)}</time>
                        </Badge>
                      )}
                    </div>
                    <CatalogSchemaDiff value={catalogStats?.schema_diff} />
                  </>
                )}
              </div>
            </Panel>
          }
        >
          <Tabs defaultValue="structure">
            <TabsList className={ws.tabList}>
              <TabsTrigger value="structure">字段结构</TabsTrigger>
              <TabsTrigger value="profile">安全画像</TabsTrigger>
              <TabsTrigger value="history">同步记录</TabsTrigger>
            </TabsList>
            <TabsContent value="structure" className={ws.tabContent}>
              {detailQuery.isError ? (
                <WorkspaceNotice
                  retry={() => {
                    void detailQuery.refetch()
                  }}
                  pending={detailQuery.isFetching}
                >
                  {formatApiError(detailQuery.error, '表结构读取失败')}
                </WorkspaceNotice>
              ) : null}
              <Panel variant="seamless" className={cn(dbCatalogPanelClass, 'flex min-h-0 min-w-0 flex-col p-0')}>
                <div className="flex shrink-0 items-start justify-between gap-3 border-b border-border/60 bg-card/65 px-3.5 py-3 dark:border-border/60 dark:bg-muted/20">
                  <div className="min-w-0 space-y-1.5">
                    <div className="text-sm font-semibold text-foreground dark:text-foreground">表结构</div>
                    {selectedSummary}
                  </div>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto p-3 no-scrollbar">
                  {(() => {
                    if (activeTableId === null ? catalogTablesQuery.isPending : detailQuery.isPending) {
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
                          {selected.columns.length > 0 ? (
                            <div className="divide-y divide-border/60 dark:divide-border/60">
                              {selected.columns.map((c) => (
                                <div key={c.id} className="grid grid-cols-12 gap-0 text-xs hover:bg-info/5">
                                  <div className="col-span-5 truncate px-3 py-2.5 font-mono text-foreground dark:text-foreground">
                                    {c.name}
                                  </div>
                                  <div className="col-span-4 truncate px-3 py-2.5 font-mono text-muted-foreground">
                                    {c.data_type || '—'}
                                  </div>
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
                    if (detailQuery.isError || catalogTablesQuery.isError) return null
                    return (
                      <div className={ws.empty}>
                        <h2>
                          {items.length ? '选择数据库表' : hasCatalogFilters ? '没有匹配的表' : '尚未同步数据库目录'}
                        </h2>
                        <p>
                          {items.length
                            ? '从目录选择一张表，查看字段与安全画像。'
                            : hasCatalogFilters
                              ? '调整搜索或引擎筛选后重试。'
                              : '建立数据库连接后，同步表结构与安全统计。'}
                        </p>
                        {items.length === 0 ? (
                          <Button
                            variant="outline"
                            onClick={() => {
                              if (hasCatalogFilters) {
                                setQuery('')
                                setEngine('all')
                              } else setSyncOpen(true)
                            }}
                          >
                            {hasCatalogFilters ? '清除筛选' : '新建同步'}
                          </Button>
                        ) : null}
                      </div>
                    )
                  })()}
                </div>
              </Panel>
            </TabsContent>
            <TabsContent value="profile" className={ws.tabContent}>
              <section className={ws.section}>
                <h2 className={ws.sectionTitle}>最新安全画像</h2>
                {latestProfileQuery.isError ? (
                  <WorkspaceNotice
                    retry={() => {
                      void latestProfileQuery.refetch()
                    }}
                    pending={latestProfileQuery.isFetching}
                  >
                    {formatApiError(latestProfileQuery.error, '安全画像读取失败')}
                  </WorkspaceNotice>
                ) : latestProfile ? (
                  <>
                    <p className="my-3 text-xs text-muted-foreground">{latestProfile.created_at}</p>
                    <pre className="overflow-auto bg-muted/20 p-3 text-xs leading-6">
                      {JSON.stringify(latestProfile.profile, null, 2)}
                    </pre>
                    <details className="mt-4 text-sm">
                      <summary>采样信息</summary>
                      <pre className="overflow-auto py-3 text-xs">
                        {JSON.stringify(latestProfile.sample_meta, null, 2)}
                      </pre>
                    </details>
                  </>
                ) : (
                  <p className="py-4 text-sm text-muted-foreground">
                    {activeTableId === null
                      ? '从目录选择一张表，查看安全画像。'
                      : latestProfileQuery.isPending
                        ? '正在读取画像…'
                        : '当前表没有安全画像记录。'}
                  </p>
                )}
              </section>
            </TabsContent>
            <TabsContent value="history" className={ws.tabContent}>
              <section className={ws.section}>
                <div className={ws.sectionHeading}>
                  <h2 className={ws.sectionTitle}>同步记录</h2>
                  <Button
                    variant="ghost"
                    disabled={isLoading || latestRunQuery.isFetching}
                    onClick={() => {
                      refreshCatalogList()
                      void latestRunQuery.refetch()
                    }}
                  >
                    重新读取记录
                  </Button>
                </div>
                {latestRunQuery.isError && (
                  <WorkspaceNotice>{formatApiError(latestRunQuery.error, '同步记录读取失败')}</WorkspaceNotice>
                )}
                {latestRunQuery.isPending && <p className={ws.muted}>正在读取同步记录…</p>}
                {catalogRuns?.length === 0 && <p className={ws.muted}>最近的运行中没有数据库目录同步记录。</p>}
                {catalogRuns !== undefined && catalogRuns.length > 0 && (
                  <div className={ws.tableScroll}>
                    <table className={ws.table} aria-label="数据库目录同步记录">
                      <thead>
                        <tr>
                          <th>运行</th>
                          <th>连接器</th>
                          <th>状态</th>
                          <th>创建时间</th>
                        </tr>
                      </thead>
                      <tbody>
                        {catalogRuns.map((run) => (
                          <tr key={run.id}>
                            <td className="font-mono text-xs">{run.id.slice(0, 8)}</td>
                            <td>{run.connector_id}</td>
                            <td>{run.status}</td>
                            <td>{run.created_at}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </TabsContent>
          </Tabs>
        </DirectoryWorkspace>
        <Dialog
          open={syncOpen}
          onOpenChange={(open) => {
            if (!open && syncRequestRef.current !== null) return
            setSyncOpen(open)
            if (!open) setSyncError(null)
          }}
        >
          <DialogContent className={ws.dialog} showCloseButton={!syncSubmitting}>
            <DialogHeader className={ws.dialogHeader}>
              <DialogTitle>数据库目录同步</DialogTitle>
              <DialogDescription>
                仅同步结构与安全画像（聚合统计）；不读取原始行，不向大模型外发数据库行数据。
              </DialogDescription>
            </DialogHeader>

            <form id="db-catalog-sync" className={ws.dialogBody} onSubmit={submitSync}>
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">连接器</legend>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant={syncConnectorId === 'sqlserver_catalog' ? 'secondary' : 'outline'}
                    size="sm"
                    className="font-mono"
                    aria-pressed={syncConnectorId === 'sqlserver_catalog'}
                    onClick={() => selectSyncConnector('sqlserver_catalog')}
                  >
                    sqlserver
                  </Button>
                  <Button
                    type="button"
                    variant={syncConnectorId === 'mysql_catalog' ? 'secondary' : 'outline'}
                    size="sm"
                    className="font-mono"
                    aria-pressed={syncConnectorId === 'mysql_catalog'}
                    onClick={() => selectSyncConnector('mysql_catalog')}
                  >
                    mysql
                  </Button>
                </div>
              </fieldset>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="space-y-2 sm:col-span-2">
                  <Label htmlFor="db-catalog-sync-host">主机</Label>
                  <Input
                    id="db-catalog-sync-host"
                    value={syncHost}
                    onChange={(e) => setSyncHost(e.target.value)}
                    placeholder="db.example.com"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="db-catalog-sync-port">端口</Label>
                  <Input
                    id="db-catalog-sync-port"
                    type="number"
                    min={1}
                    max={65535}
                    step={1}
                    required
                    value={syncPort}
                    onChange={(event) => setSyncPort(event.target.value)}
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="db-catalog-sync-database">数据库</Label>
                  <Input
                    id="db-catalog-sync-database"
                    value={syncDatabase}
                    onChange={(e) => setSyncDatabase(e.target.value)}
                    placeholder="demo"
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="db-catalog-sync-username">用户名</Label>
                  <Input
                    id="db-catalog-sync-username"
                    value={syncUsername}
                    onChange={(e) => setSyncUsername(e.target.value)}
                    placeholder="svc_reader"
                    required
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="db-catalog-sync-password">密码</Label>
                <Input
                  id="db-catalog-sync-password"
                  type="password"
                  value={syncPassword}
                  readOnly={syncSubmitting}
                  onChange={(e) => setSyncPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="new-password"
                  required
                />
              </div>

              {syncConnectorId === 'sqlserver_catalog' ? (
                <div className="space-y-2">
                  <Label htmlFor="db-catalog-sync-schemas">Schema 范围（选填）</Label>
                  <Textarea
                    id="db-catalog-sync-schemas"
                    value={syncIncludeSchemas}
                    onChange={(e) => setSyncIncludeSchemas(e.target.value)}
                    placeholder="dbo\nsales"
                    rows={2}
                  />
                </div>
              ) : null}

              <div className="space-y-2">
                <Label htmlFor="db-catalog-sync-tables">同步表范围（选填）</Label>
                <Textarea
                  id="db-catalog-sync-tables"
                  value={syncIncludeTables}
                  onChange={(e) => setSyncIncludeTables(e.target.value)}
                  placeholder={syncConnectorId === 'sqlserver_catalog' ? 'dbo.users\ndbo.orders' : 'users\norders'}
                  rows={3}
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="db-catalog-sync-max-tables">最大表数</Label>
                  <Input
                    id="db-catalog-sync-max-tables"
                    type="number"
                    min={1}
                    max={2000}
                    step={1}
                    required
                    value={syncMaxTables}
                    onChange={(event) => setSyncMaxTables(event.target.value)}
                  />
                </div>
                <div className="rounded-xl border border-border bg-muted/20 px-4 py-3 flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <Label htmlFor="db-catalog-sync-profile">安全画像</Label>
                    <div className="text-xs text-muted-foreground text-pretty truncate">
                      记录 row_count_estimate 等聚合统计
                    </div>
                  </div>
                  <Switch
                    id="db-catalog-sync-profile"
                    checked={syncProfileEnabled}
                    onCheckedChange={setSyncProfileEnabled}
                  />
                </div>
              </div>

              {syncError ? <WorkspaceNotice>{syncError}</WorkspaceNotice> : null}
            </form>

            <DialogFooter className={ws.dialogFooter}>
              <Button type="button" variant="outline" onClick={() => setSyncOpen(false)} disabled={syncSubmitting}>
                取消
              </Button>
              <Button type="submit" form="db-catalog-sync" disabled={syncSubmitting}>
                <Play className="h-4 w-4" />
                {syncSubmitting ? '正在创建...' : '开始同步'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </OperationalWorkspace>
    </AppFrame>
  )
}
