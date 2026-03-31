'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'next/navigation'
import { toast } from 'sonner'
import { ArrowLeft, Database, Play, RefreshCw, Settings2 } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useRouter } from '@/i18n/navigation'
import { formatApiError } from '@/lib/api-errors'
import { connectorApi, datasetApi } from '@/lib/api'
import { cn, detachPromise } from '@/lib/utils'

import type { ConnectorRunOut, Dataset, DbCatalogTableDetail, DbCatalogTableSummary, DbProfileSnapshot } from '@/types'

const ENGINE_OPTIONS: ReadonlyArray<'all' | 'mysql' | 'sqlserver'> = ['all', 'mysql', 'sqlserver']

function asDatasetId(raw: unknown): string | null {
  if (typeof raw === 'string' && raw.trim()) return raw
  if (Array.isArray(raw) && typeof raw[0] === 'string') return raw[0]
  return null
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
  const router = useRouter()
  const params = useParams()
  const datasetId = asDatasetId((params as any)?.id)

  const [dataset, setDataset] = useState<Dataset | null>(null)

  const [engine, setEngine] = useState<'all' | 'mysql' | 'sqlserver'>('all')
  const [query, setQuery] = useState('')

  const [isLoading, setIsLoading] = useState(false)
  const [items, setItems] = useState<DbCatalogTableSummary[]>([])

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selected, setSelected] = useState<DbCatalogTableDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [latestProfile, setLatestProfile] = useState<DbProfileSnapshot | null>(null)

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

  const [latestRun, setLatestRun] = useState<ConnectorRunOut | null>(null)
  const [latestRunLoading, setLatestRunLoading] = useState(false)

  const loadLatestRun = useCallback(async () => {
    if (!datasetId) return
    setLatestRunLoading(true)
    try {
      const res = await connectorApi.listRuns({ dataset_id: datasetId, limit: 10 })
      const items = res.items || []
      const catalog = items.filter((r) => ['mysql_catalog', 'sqlserver_catalog'].includes(String(r.connector_id || '').toLowerCase()))
      setLatestRun(catalog[0] || null)
    } catch {
      // Likely permission-gated (requires dataset write). Fail closed.
      setLatestRun(null)
    } finally {
      setLatestRunLoading(false)
    }
  }, [datasetId])

  const loadList = useCallback(async () => {
    if (!datasetId) return
    setIsLoading(true)
    try {
      const [ds, list] = await Promise.all([
        datasetApi.get(datasetId),
        datasetApi.listDbCatalogTables(datasetId, {
          skip: 0,
          limit: 200,
          engine: engine === 'all' ? undefined : engine,
          q: query.trim() ? query.trim() : undefined,
        }),
      ])
      setDataset(ds)
      const nextItems = list.items || []
      setItems(nextItems)
      setSelectedId((prev) => {
        if (prev && nextItems.some((t) => t.id === prev)) return prev
        return nextItems[0]?.id || null
      })
    } catch (e: any) {
      console.error('Failed to load DB catalog', e)
      toast.error(formatApiError(e, '加载数据库目录失败'))
    } finally {
      setIsLoading(false)
    }
  }, [datasetId, engine, query])

  const loadDetail = useCallback(
    async (tableId: string) => {
      if (!datasetId) return
      setDetailLoading(true)
      setLatestProfile(null)
      try {
        const entitlementHash =
          typeof (latestRun as any)?.stats?.result?.entitlement_hash === 'string'
            ? ((latestRun as any).stats.result.entitlement_hash as string)
            : undefined

        const [detailRes, profileRes] = await Promise.allSettled([
          datasetApi.getDbCatalogTable(datasetId, tableId),
          datasetApi.listDbCatalogProfiles(datasetId, {
            table_id: tableId,
            entitlement_hash: entitlementHash,
            skip: 0,
            limit: 1,
          }),
        ])

        if (detailRes.status === 'fulfilled') {
          setSelected(detailRes.value)
        } else {
          setSelected(null)
          toast.error(formatApiError(detailRes.reason, '加载表结构失败'))
          return
        }

        if (profileRes.status === 'fulfilled') {
          setLatestProfile((profileRes.value.items || [])[0] || null)
        } else {
          setLatestProfile(null)
        }
      } catch (e: any) {
        console.error('Failed to load DB catalog table detail', e)
        setSelected(null)
        setLatestProfile(null)
        toast.error(formatApiError(e, '加载表结构失败'))
      } finally {
        setDetailLoading(false)
      }
    },
    [datasetId, latestRun]
  )

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

    const cfg: any = {
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
      toast.success(`已创建同步任务：${run.id.slice(0, 8)}`)
      setLatestRun(run)
      setSyncOpen(false)
      setSyncPassword('')
      // Best-effort: refresh after a short delay (sync runs async).
      globalThis.window.setTimeout(() => {
        detachPromise(loadList())
        detachPromise(loadLatestRun())
      }, 1500)
    } catch (e: any) {
      console.error('Failed to create DB catalog run', e)
      setSyncError(formatApiError(e, '创建同步任务失败'))
    } finally {
      setSyncSubmitting(false)
    }
  }, [
    datasetId,
    loadList,
    loadLatestRun,
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
  ])

  useEffect(() => {
    loadList()
  }, [loadList])

  useEffect(() => {
    detachPromise(loadLatestRun())
  }, [loadLatestRun])

  useEffect(() => {
    if (!selectedId) {
      setSelected(null)
      return
    }
    loadDetail(selectedId)
  }, [selectedId, loadDetail])

  const selectedSummary = useMemo(() => {
    if (!selected) return null
    const name = formatQualifiedName(selected)
    const rowCount = (() => {
      const v = latestProfile?.profile?.row_count_estimate
      if (v === null || v === undefined) return null
      if (typeof v === 'number' && Number.isFinite(v)) return v
      const n = Number.parseInt(String(v), 10)
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

  return (
    <AppFrame>
      <PageScaffold
        title="数据库目录 / Catalog"
        badge="DB Catalog"
        icon={Database}
        iconColor="text-teal"
        description={
          dataset ? (
            <span className="font-mono text-xs">
              Dataset: <span className="text-foreground font-semibold">{dataset.name}</span>
            </span>
          ) : (
            <span className="font-mono text-xs">DB Catalog</span>
          )
        }
        actions={
          <div className="flex items-center gap-2">
            <Button variant="ghost" className="gap-2" onClick={() => router.push('/datasets')}>
              <ArrowLeft className="h-4 w-4" />
              返回
            </Button>
            {datasetId ? (
              <>
                <Button
                  variant="outline"
                  className="gap-2"
                  onClick={() => router.push(`/knowledge?tab=settings&dataset=${encodeURIComponent(datasetId)}`)}
                >
                  <Settings2 className="h-4 w-4" />
                  导入任务
                </Button>
                <Button
                  className="gap-2"
                  onClick={() => {
                    setSyncError(null)
                    setSyncOpen(true)
                  }}
                >
                  <Play className="h-4 w-4" />
                  新建同步
                </Button>
              </>
            ) : null}
            <Button variant="outline" className="gap-2" onClick={loadList} disabled={isLoading}>
              <RefreshCw className="h-4 w-4" />
              刷新
            </Button>
          </div>
        }
      >
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          <Panel className="lg:col-span-4" padding="lg">
            <div className="space-y-4">
              <div className="rounded-xl border border-border/60 bg-background/60 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-foreground">最近同步</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      需要数据集写权限才可查看运行记录与 diff。
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-2"
                    onClick={() => detachPromise(loadLatestRun())}
                    disabled={latestRunLoading}
                  >
                    <RefreshCw className={cn('h-3.5 w-3.5', latestRunLoading && 'animate-spin motion-reduce:animate-none')} />
                    刷新
                  </Button>
                </div>

                {latestRun ? (
                  <div className="mt-3 space-y-2 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className="font-mono">
                        {latestRun.status}
                      </Badge>
                      <Badge variant="soft" className="font-mono">
                        {latestRun.connector_id}
                      </Badge>
                      <Badge variant="soft" className="font-mono">
                        run {latestRun.id.slice(0, 8)}
                      </Badge>
                    </div>

                    {(() => {
                      const stats: any = latestRun.stats || {}
                      const result: any = stats.result || {}
                      const schemaDoc: any = stats.schema_doc || {}
                      const diff: any = schemaDoc.schema_diff || {}

                      const ageSecRaw = schemaDoc.catalog_age_sec
                      const ageSec = typeof ageSecRaw === 'number' && Number.isFinite(ageSecRaw) ? ageSecRaw : null
                      const ageText =
                        (() => {
    if (ageSec === null) {
        return null;
    }
    else if (ageSec < 90) {
            return `${Math.round(ageSec)}s`;
        }
        else if (ageSec < 3600) {
                return `${Math.round(ageSec / 60)}m`;
            }
            else {
                return `${Math.round(ageSec / 3600)}h`;
            }
})()

                      const tables = Number(result.tables ?? schemaDoc.tables ?? 0)
                      const cols = Number(result.columns_upserted ?? schemaDoc.columns ?? 0)
                      const profiles = Number(result.profiles_written ?? schemaDoc.tables_with_profiles ?? 0)

                      const ta = Number(diff?.tables_added?.count ?? 0)
                      const tr = Number(diff?.tables_removed?.count ?? 0)
                      const ca = Number(diff?.columns_added?.count ?? 0)
                      const cr = Number(diff?.columns_removed?.count ?? 0)
                      const cc = Number(diff?.columns_changed?.count ?? 0)
                      const taItems: string[] = Array.isArray(diff?.tables_added?.items) ? diff.tables_added.items : []
                      const trItems: string[] = Array.isArray(diff?.tables_removed?.items) ? diff.tables_removed.items : []
                      const caItems: string[] = Array.isArray(diff?.columns_added?.items) ? diff.columns_added.items : []
                      const crItems: string[] = Array.isArray(diff?.columns_removed?.items) ? diff.columns_removed.items : []
                      const ccItems: any[] = Array.isArray(diff?.columns_changed?.items) ? diff.columns_changed.items : []

                      return (
                        <>
                          <div className="flex flex-wrap gap-2">
                            <Badge variant="soft" className="font-mono tabular-nums">
                              tables: {Number.isFinite(tables) ? tables : 0}
                            </Badge>
                            <Badge variant="soft" className="font-mono tabular-nums">
                              cols: {Number.isFinite(cols) ? cols : 0}
                            </Badge>
                            <Badge variant="soft" className="font-mono tabular-nums">
                              profiles: {Number.isFinite(profiles) ? profiles : 0}
                            </Badge>
                            {ageText ? (
                              <Badge variant="soft" className="font-mono tabular-nums">
                                freshness: {ageText}
                              </Badge>
                            ) : null}
                          </div>

                          {ta + tr + ca + cr + cc > 0 ? (
                            <>
                              <div className="flex flex-wrap gap-2">
                                <Badge variant={ta > 0 ? 'default' : 'soft'} className="font-mono tabular-nums">
                                  +tables {ta}
                                </Badge>
                                <Badge variant={tr > 0 ? 'destructive' : 'soft'} className="font-mono tabular-nums">
                                  -tables {tr}
                                </Badge>
                                <Badge variant={ca > 0 ? 'default' : 'soft'} className="font-mono tabular-nums">
                                  +cols {ca}
                                </Badge>
                                <Badge variant={cr > 0 ? 'destructive' : 'soft'} className="font-mono tabular-nums">
                                  -cols {cr}
                                </Badge>
                                <Badge variant={cc > 0 ? 'secondary' : 'soft'} className="font-mono tabular-nums">
                                  ~cols {cc}
                                </Badge>
                              </div>

                              {taItems.length || trItems.length || caItems.length || crItems.length || ccItems.length ? (
                                <details className="rounded-lg border border-border/60 bg-background/40 px-3 py-2">
                                  <summary className="cursor-pointer select-none text-xs text-muted-foreground">
                                    查看 diff 详情（最多展示部分）
                                  </summary>
                                  <div className="mt-2 space-y-2 text-[12px]">
                                    {taItems.length ? (
                                      <div>
                                        <div className="font-semibold text-foreground">新增表</div>
                                        <div className="mt-1 font-mono text-muted-foreground break-words">
                                          {taItems.join(', ')}
                                        </div>
                                      </div>
                                    ) : null}
                                    {trItems.length ? (
                                      <div>
                                        <div className="font-semibold text-foreground">删除表</div>
                                        <div className="mt-1 font-mono text-muted-foreground break-words">
                                          {trItems.join(', ')}
                                        </div>
                                      </div>
                                    ) : null}
                                    {caItems.length ? (
                                      <div>
                                        <div className="font-semibold text-foreground">新增列</div>
                                        <div className="mt-1 font-mono text-muted-foreground break-words">
                                          {caItems.join(', ')}
                                        </div>
                                      </div>
                                    ) : null}
                                    {crItems.length ? (
                                      <div>
                                        <div className="font-semibold text-foreground">删除列</div>
                                        <div className="mt-1 font-mono text-muted-foreground break-words">
                                          {crItems.join(', ')}
                                        </div>
                                      </div>
                                    ) : null}
                                    {ccItems.length ? (
                                      <div>
                                        <div className="font-semibold text-foreground">变更列</div>
                                        <div className="mt-1 space-y-1 font-mono text-muted-foreground">
                                          {ccItems.slice(0, 20).map((it) => {
                                            const key = `${it?.table || ''}.${it?.column || ''}`
                                            return (
                                              <div key={key} className="break-words">
                                                {key} ({String(it?.old?.data_type || '')} → {String(it?.new?.data_type || '')})
                                              </div>
                                            )
                                          })}
                                        </div>
                                      </div>
                                    ) : null}
                                  </div>
                                </details>
                              ) : null}
                            </>
                          ) : null}
                        </>
                      )
                    })()}
                  </div>
                ) : (
                  <div className="mt-3 text-xs text-muted-foreground">暂无同步记录（或无权限）。</div>
                )}
              </div>

              <div className="space-y-2">
                <Label className="text-sm">搜索</Label>
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="db/schema/table"
                />
              </div>

              <div className="flex flex-wrap gap-2">
                {ENGINE_OPTIONS.map((k) => (
                  <Button
                    key={k}
                    type="button"
                    variant={engine === k ? 'secondary' : 'outline'}
                    size="sm"
                    className={cn('font-mono', engine === k ? 'border-border' : undefined)}
                    onClick={() => setEngine(k)}
                  >
                    {k}
                  </Button>
                ))}
              </div>

              <div className="border-t border-border pt-3">
                {(() => {
    if (isLoading) {
        return (<div className="space-y-2">
                    <Skeleton className="h-9 w-full"/>
                    <Skeleton className="h-9 w-full"/>
                    <Skeleton className="h-9 w-full"/>
                    <Skeleton className="h-9 w-full"/>
                  </div>);
    }
    else if (items.length) {
            return (<div className="space-y-1">
                    {items.map((t) => {
                    const active = t.id === selectedId;
                    return (<button key={t.id} type="button" className={cn('w-full text-left rounded-lg px-3 py-2 border transition duration-200', active ? 'border-primary/50 bg-primary/5' : 'border-border hover:bg-muted/40')} onClick={() => setSelectedId(t.id)}>
                          <div className="flex items-center justify-between gap-3">
                            <div className="min-w-0">
                              <div className="font-mono text-xs truncate tabular-nums">{formatQualifiedName(t)}</div>
                              <div className="text-xs text-muted-foreground truncate text-pretty">
                                {t.comment || '—'}
                              </div>
                            </div>
                            <Badge variant="outline" className="font-mono text-[10px]">
                              {t.engine}
                            </Badge>
                          </div>
                        </button>);
                })}
                  </div>);
        }
        else {
            return (<div className="rounded-xl border border-dashed border-border p-4 bg-muted/30">
                    <div className="text-sm font-medium">暂无数据库目录</div>
                    <div className="text-xs text-muted-foreground mt-1 text-pretty">
                      先运行 SQLServer/MySQL 目录同步（只同步结构与安全统计，不读取原始行）。
                    </div>
                    {datasetId ? (<div className="mt-3">
                        <Button variant="outline" className="gap-2" onClick={() => {
                        setSyncError(null);
                        setSyncOpen(true);
                    }}>
                          <Play className="h-4 w-4"/>
                          新建同步
                        </Button>
                      </div>) : null}
                  </div>);
        }
})()}
              </div>
            </div>
          </Panel>

          <Panel className="lg:col-span-8" padding="lg">
            <div className="space-y-4">
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-2">
                  <div className="text-sm font-medium">表结构</div>
                  {selectedSummary}
                </div>
              </div>

              {(() => {
    if (detailLoading) {
        return (<div className="space-y-2">
                  <Skeleton className="h-7 w-40"/>
                  <Skeleton className="h-10 w-full"/>
                  <Skeleton className="h-10 w-full"/>
                  <Skeleton className="h-10 w-full"/>
                </div>);
    }
    else if (selected) {
            return (<div className="rounded-xl border border-border overflow-hidden">
                  <div className="grid grid-cols-12 gap-0 bg-muted/40 text-xs font-medium">
                    <div className="col-span-5 px-3 py-2">Column</div>
                    <div className="col-span-4 px-3 py-2">Type</div>
                    <div className="col-span-3 px-3 py-2">Nullable</div>
                  </div>
                  {selected.columns?.length ? (<div className="divide-y divide-border">
                      {selected.columns.map((c) => (<div key={c.id} className="grid grid-cols-12 gap-0 text-xs">
                          <div className="col-span-5 px-3 py-2 font-mono truncate">{c.name}</div>
                          <div className="col-span-4 px-3 py-2 font-mono text-muted-foreground truncate">
                            {c.data_type || '—'}
                          </div>
                          <div className="col-span-3 px-3 py-2 font-mono text-muted-foreground">
                            {(() => {
                        if (c.nullable === null || c.nullable === undefined) {
                            return '—';
                        }
                        else if (c.nullable) {
                                return 'true';
                            }
                            else {
                                return 'false';
                            }
                    })()}
                          </div>
                        </div>))}
                    </div>) : (<div className="p-4 text-sm text-muted-foreground text-pretty">暂无列信息（可能尚未完成同步）。</div>)}
                </div>);
        }
        else {
            return (<div className="rounded-xl border border-dashed border-border p-6 bg-muted/30 text-sm text-muted-foreground text-pretty">
                  请选择一张表查看结构。
                </div>);
        }
})()}
            </div>
          </Panel>
        </div>

        <Dialog
          open={syncOpen}
          onOpenChange={(open) => {
            setSyncOpen(open)
            if (!open) setSyncError(null)
          }}
        >
          <DialogContent className="max-w-xl">
            <DialogHeader>
              <DialogTitle>DB 目录同步</DialogTitle>
              <DialogDescription>
                仅同步结构与安全画像（聚合统计）；不读取原始行，不向大模型外发数据库行数据。
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4">
              <div className="space-y-2">
                <Label>Connector</Label>
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
                  <Label>Host</Label>
                  <Input value={syncHost} onChange={(e) => setSyncHost(e.target.value)} placeholder="db.example.com" />
                </div>
                <div className="space-y-2">
                  <Label>Port</Label>
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
                  <Label>Database</Label>
                  <Input value={syncDatabase} onChange={(e) => setSyncDatabase(e.target.value)} placeholder="demo" />
                </div>
                <div className="space-y-2">
                  <Label>Username</Label>
                  <Input value={syncUsername} onChange={(e) => setSyncUsername(e.target.value)} placeholder="svc_reader" />
                </div>
              </div>

              <div className="space-y-2">
                <Label>Password</Label>
                <Input
                  type="password"
                  value={syncPassword}
                  onChange={(e) => setSyncPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="new-password"
                />
              </div>

              {syncConnectorId === 'sqlserver_catalog' ? (
                <div className="space-y-2">
                  <Label>Include Schemas (optional)</Label>
                  <Textarea
                    value={syncIncludeSchemas}
                    onChange={(e) => setSyncIncludeSchemas(e.target.value)}
                    placeholder="dbo\nsales"
                    rows={2}
                  />
                </div>
              ) : null}

              <div className="space-y-2">
                <Label>Include Tables (optional)</Label>
                <Textarea
                  value={syncIncludeTables}
                  onChange={(e) => setSyncIncludeTables(e.target.value)}
                  placeholder={syncConnectorId === 'sqlserver_catalog' ? 'dbo.users\ndbo.orders' : 'users\norders'}
                  rows={3}
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label>Max Tables</Label>
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

              {syncError ? <div className="text-sm text-destructive text-pretty">{syncError}</div> : null}
            </div>

            <DialogFooter>
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
      </PageScaffold>
    </AppFrame>
  )
}
