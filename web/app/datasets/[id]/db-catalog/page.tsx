'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
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
import { formatApiError } from '@/lib/api-errors'
import { connectorApi, datasetApi } from '@/lib/api-client'
import { cn } from '@/lib/utils'

import type { Dataset, DbCatalogTableDetail, DbCatalogTableSummary, DbProfileSnapshot } from '@/types'

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
        const [detailRes, profileRes] = await Promise.allSettled([
          datasetApi.getDbCatalogTable(datasetId, tableId),
          datasetApi.listDbCatalogProfiles(datasetId, { table_id: tableId, skip: 0, limit: 1 }),
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
    [datasetId]
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
      port: Number.isFinite(syncPort) ? Math.trunc(syncPort) : syncConnectorId === 'sqlserver_catalog' ? 1433 : 3306,
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
      setSyncOpen(false)
      setSyncPassword('')
      // Best-effort: refresh after a short delay (sync runs async).
      window.setTimeout(() => {
        void loadList()
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
        {rowCount !== null ? (
          <Badge variant="soft" className="font-mono tabular-nums">
            rows~: {rowCount.toLocaleString()}
          </Badge>
        ) : null}
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
        iconColor="text-primary"
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
              <div className="space-y-2">
                <Label className="text-sm">搜索</Label>
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="db/schema/table"
                />
              </div>

              <div className="flex flex-wrap gap-2">
                {(['all', 'mysql', 'sqlserver'] as const).map((k) => (
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
                {isLoading ? (
                  <div className="space-y-2">
                    <Skeleton className="h-9 w-full" />
                    <Skeleton className="h-9 w-full" />
                    <Skeleton className="h-9 w-full" />
                    <Skeleton className="h-9 w-full" />
                  </div>
                ) : items.length ? (
                  <div className="space-y-1">
                    {items.map((t) => {
                      const active = t.id === selectedId
                      return (
                        <button
                          key={t.id}
                          type="button"
                          className={cn(
                            'w-full text-left rounded-lg px-3 py-2 border transition duration-200',
                            active ? 'border-primary/50 bg-primary/5' : 'border-border hover:bg-muted/40'
                          )}
                          onClick={() => setSelectedId(t.id)}
                        >
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
                        </button>
                      )
                    })}
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-border p-4 bg-muted/30">
                    <div className="text-sm font-medium">暂无数据库目录</div>
                    <div className="text-xs text-muted-foreground mt-1 text-pretty">
                      先运行 SQLServer/MySQL 目录同步（只同步结构与安全统计，不读取原始行）。
                    </div>
                    {datasetId ? (
                      <div className="mt-3">
                        <Button
                          variant="outline"
                          className="gap-2"
                          onClick={() => {
                            setSyncError(null)
                            setSyncOpen(true)
                          }}
                        >
                          <Play className="h-4 w-4" />
                          新建同步
                        </Button>
                      </div>
                    ) : null}
                  </div>
                )}
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

              {detailLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-7 w-40" />
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                </div>
              ) : selected ? (
                <div className="rounded-xl border border-border overflow-hidden">
                  <div className="grid grid-cols-12 gap-0 bg-muted/40 text-xs font-medium">
                    <div className="col-span-5 px-3 py-2">Column</div>
                    <div className="col-span-4 px-3 py-2">Type</div>
                    <div className="col-span-3 px-3 py-2">Nullable</div>
                  </div>
                  {selected.columns?.length ? (
                    <div className="divide-y divide-border">
                      {selected.columns.map((c) => (
                        <div key={c.id} className="grid grid-cols-12 gap-0 text-xs">
                          <div className="col-span-5 px-3 py-2 font-mono truncate">{c.name}</div>
                          <div className="col-span-4 px-3 py-2 font-mono text-muted-foreground truncate">
                            {c.data_type || '—'}
                          </div>
                          <div className="col-span-3 px-3 py-2 font-mono text-muted-foreground">
                            {c.nullable === null || c.nullable === undefined ? '—' : c.nullable ? 'true' : 'false'}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="p-4 text-sm text-muted-foreground text-pretty">暂无列信息（可能尚未完成同步）。</div>
                  )}
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-border p-6 bg-muted/30 text-sm text-muted-foreground text-pretty">
                  请选择一张表查看结构。
                </div>
              )}
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
