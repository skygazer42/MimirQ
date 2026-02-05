'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { ArrowLeft, Database, RefreshCw, Table2 } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Skeleton } from '@/components/ui/skeleton'
import { formatApiError } from '@/lib/api-errors'
import { datasetApi } from '@/lib/api-client'
import { cn } from '@/lib/utils'

import type { Dataset, DbCatalogTableDetail, DbCatalogTableSummary } from '@/types'

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
      try {
        const detail = await datasetApi.getDbCatalogTable(datasetId, tableId)
        setSelected(detail)
      } catch (e: any) {
        console.error('Failed to load DB catalog table detail', e)
        setSelected(null)
        toast.error(formatApiError(e, '加载表结构失败'))
      } finally {
        setDetailLoading(false)
      }
    },
    [datasetId]
  )

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
        {selected.columns?.length ? (
          <Badge variant="soft" className="font-mono tabular-nums">
            cols: {selected.columns.length}
          </Badge>
        ) : null}
      </div>
    )
  }, [selected])

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
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                <Table2 className="h-4 w-4" />
                去数据录入
              </Button>
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
                      先在「数据录入」里运行 SQLServer/MySQL 目录同步（只同步结构与安全统计，不读取原始行）。
                    </div>
                    {datasetId ? (
                      <div className="mt-3">
                        <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                          <Table2 className="h-4 w-4" />
                          去配置连接器
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
      </PageScaffold>
    </AppFrame>
  )
}

