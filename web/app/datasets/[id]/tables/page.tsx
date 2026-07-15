'use client'

import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, BarChart3, Cloud, Database, FileSearch, Play, Sparkles, Table2 } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useRouter } from '@/i18n/navigation'
import { formatApiError } from '@/lib/api-errors'
import { datasetApi } from '@/lib/api'
import { reportClientError } from '@/lib/client-logging'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

import type { Dataset, DatasetTableAsset, TableAskResponse, TableQueryResponse } from '@/types'

function asDatasetId(raw: unknown): string | null {
  if (typeof raw === 'string' && raw.trim()) return raw
  if (Array.isArray(raw) && typeof raw[0] === 'string') return raw[0]
  return null
}

function renderValue(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    return JSON.stringify(v)
  } catch {
    return toTrimmedPrimitiveString(v)
  }
}

const TABLE_ASSET_LIST_PARAMS = { skip: 0, limit: 200 } as const

export default function DatasetTablesPage() {
  const router = useRouter()
  const params = useParams()
  const datasetId = asDatasetId((params as Record<string, unknown>)?.id)

  const [selected, setSelected] = useState<DatasetTableAsset | null>(null)

  const [querySql, setQuerySql] = useState('SELECT * FROM "sheet_0" LIMIT 20')
  const [queryRes, setQueryRes] = useState<TableQueryResponse | null>(null)
  const [queryRunning, setQueryRunning] = useState(false)

  const [question, setQuestion] = useState('')
  const [askRes, setAskRes] = useState<TableAskResponse | null>(null)
  const [askRunning, setAskRunning] = useState(false)

  const [semFilterInstruction, setSemFilterInstruction] = useState('')
  const [semFilterRes, setSemFilterRes] = useState<TableQueryResponse | null>(null)
  const [semFilterRunning, setSemFilterRunning] = useState(false)

  const datasetQuery = useQuery({
    queryKey: queryKeys.datasets.detail(datasetId || ''),
    queryFn: () => {
      if (!datasetId) throw new Error('缺少数据集 ID')
      return datasetApi.get(datasetId)
    },
    enabled: Boolean(datasetId),
  })
  const tablesQuery = useQuery({
    queryKey: queryKeys.datasets.tables(datasetId || '', TABLE_ASSET_LIST_PARAMS),
    queryFn: () => {
      if (!datasetId) throw new Error('缺少数据集 ID')
      return datasetApi.listTables(datasetId, TABLE_ASSET_LIST_PARAMS)
    },
    enabled: Boolean(datasetId),
  })
  const dataset = (datasetQuery.data ?? null) as Dataset | null
  const items: DatasetTableAsset[] = useMemo(
    () => tablesQuery.data?.items || [],
    [tablesQuery.data?.items]
  )
  const isLoading = datasetQuery.isFetching || tablesQuery.isFetching
  const loadError = datasetQuery.error ?? tablesQuery.error
  const loadErrorUpdatedAt = Math.max(
    datasetQuery.errorUpdatedAt,
    tablesQuery.errorUpdatedAt
  )

  useEffect(() => {
    if (!loadError) return
    toast.error(formatApiError(loadError, '加载表格失败'))
  }, [loadError, loadErrorUpdatedAt])

  useEffect(() => {
    setSelected((prev) => {
      if (items.length === 0) return null
      if (!prev) return items[0] || null
      const found = items.find((t) => t.table_id === prev.table_id)
      if (!found) return items[0] || null
      return {
        ...found,
        columns: prev.columns,
        sample_rows: prev.sample_rows,
      }
    })
  }, [items])

  useEffect(() => {
    if (!datasetId || !selected?.table_id) return
    if (Array.isArray(selected.columns) && selected.columns.length > 0) return

    let cancelled = false
    datasetApi
      .getTable(datasetId, selected.table_id, { include_columns: true, include_sample_rows: true })
      .then((full) => {
        if (cancelled) return
        setSelected((prev) => (prev?.table_id === full.table_id ? full : prev))
      })
      .catch((e: unknown) => {
        if (cancelled) return
        reportClientError('Failed to load selected table detail', e)
        toast.error(formatApiError(e, '加载表格详情失败'))
      })

    return () => {
      cancelled = true
    }
  }, [datasetId, selected?.columns, selected?.table_id])

  const selectTable = async (table: DatasetTableAsset) => {
    if (!datasetId) return
    setSelected(table)
    try {
      const full = await datasetApi.getTable(datasetId, table.table_id, { include_columns: true, include_sample_rows: true })
      setSelected(full)
      // Update default query target table for convenience.
      const sheetName = `sheet_${full.sheet_index || 0}`
      setQuerySql(`SELECT * FROM "${sheetName}" LIMIT 20`)
    } catch (e: unknown) {
      reportClientError('Failed to load dataset table detail', e)
      toast.error(formatApiError(e, '加载表格详情失败'))
    }
  }

  const runQuery = async () => {
    if (!datasetId || !selected) return
    setQueryRunning(true)
    setQueryRes(null)
    try {
      const res = await datasetApi.queryTable(datasetId, selected.table_id, { sql: querySql })
      setQueryRes(res)
    } catch (e: unknown) {
      reportClientError('Dataset table SQL query failed', e)
      toast.error(formatApiError(e, '查询失败（只允许 SELECT/WITH SELECT）'))
    } finally {
      setQueryRunning(false)
    }
  }

  const ask = async () => {
    if (!datasetId || !selected) return
    if (!question.trim()) return
    setAskRunning(true)
    setAskRes(null)
    try {
      const res = await datasetApi.askTable(datasetId, selected.table_id, { question: question.trim() })
      setAskRes(res)
    } catch (e: unknown) {
      reportClientError('Dataset table question answering failed', e)
      toast.error(formatApiError(e, 'TAG 问答失败（需要开启 TABLE_NL2SQL_ENABLED）'))
    } finally {
      setAskRunning(false)
    }
  }

  const semFilter = async () => {
    if (!datasetId || !selected) return
    if (!semFilterInstruction.trim()) return
    setSemFilterRunning(true)
    setSemFilterRes(null)
    try {
      const res = await datasetApi.lotusSemFilter(datasetId, selected.table_id, { user_instruction: semFilterInstruction.trim(), strategy: 'cot' })
      setSemFilterRes(res)
    } catch (e: unknown) {
      reportClientError('Dataset table semantic filter failed', e)
      toast.error(formatApiError(e, '语义过滤失败（需要开启 TABLE_LOTUS_ENABLED 或 TABLE_NL2SQL_ENABLED）'))
    } finally {
      setSemFilterRunning(false)
    }
  }

  const selectedSummary = useMemo(() => {
    if (!selected) return null
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="outline" className="font-mono">
          {selected.table_id}
        </Badge>
        <Badge variant="soft" className="font-mono">
          rows: {selected.row_count}
        </Badge>
        <Badge variant="soft" className="font-mono">
          cols: {selected.col_count}
        </Badge>
        {selected.truncated ? (
          <Badge variant="destructive" className="font-mono">
            truncated
          </Badge>
        ) : null}
        {selected.sheet_name ? (
          <Badge variant="outline" className="font-mono">
            sheet: {selected.sheet_name}
          </Badge>
        ) : null}
      </div>
    )
  }, [selected])

  const tablesHeroCard = 'relative overflow-hidden rounded-[26px] border border-border/60 bg-[linear-gradient(135deg,rgba(255,255,255,0.98),rgba(246,248,251,0.94)_45%,rgba(232,246,250,0.72))] shadow-[0_24px_70px_rgba(15,23,42,0.10)] ring-1 ring-white/80 before:pointer-events-none before:absolute before:inset-0 before:bg-[radial-gradient(circle_at_16%_10%,rgba(8,145,178,0.16),transparent_26%),radial-gradient(circle_at_82%_0%,rgba(15,23,42,0.075),transparent_24%),linear-gradient(90deg,rgba(15,23,42,0.035)_1px,transparent_1px)] before:bg-[length:auto,auto,34px_34px] dark:border-border/60 dark:bg-none dark:bg-card/95 dark:ring-white/5'
  const tablePanelClass = 'overflow-hidden rounded-[24px] border-border/60 bg-card/88 shadow-[0_18px_54px_rgba(15,23,42,0.08)] ring-1 ring-white/75 backdrop-blur-xl dark:border-border/60 dark:bg-card/82 dark:ring-white/5'
  const tablePanelHeaderClass = 'border-b border-border/60 bg-[linear-gradient(180deg,rgba(255,255,255,0.94),rgba(248,250,252,0.78))] px-5 py-4 dark:border-border/60 dark:bg-none dark:bg-muted/20'
  const sectionTitleClass = 'text-[15px] font-bold tracking-[-0.015em] text-foreground dark:text-foreground'
  const mutedHintClass = 'text-[12px] leading-5 text-muted-foreground dark:text-muted-foreground'
  const tableToolbarGroupClass = 'inline-flex flex-wrap items-center gap-1 rounded-2xl border border-border/60 bg-card/82 p-1 shadow-[0_12px_34px_rgba(15,23,42,0.07)] ring-1 ring-white/75 backdrop-blur dark:border-border/60 dark:bg-card/70 dark:ring-white/5'
  const tableToolbarButtonClass = 'h-8 gap-1.5 rounded-xl px-2.5 text-[12px] font-semibold text-muted-foreground shadow-none hover:bg-card hover:text-foreground hover:shadow-sm dark:text-muted-foreground dark:hover:bg-muted/60 dark:hover:text-foreground [&_svg]:size-3.5'
  const tableMetricCardClass = 'relative overflow-hidden rounded-2xl border border-border/60 bg-card/90 px-4 py-3 shadow-[0_12px_32px_rgba(15,23,42,0.055)] ring-1 ring-white/80 transition-colors hover:border-border dark:border-border/60 dark:bg-card/80 dark:ring-white/5'
  const tableIconPillClass = 'flex size-9 shrink-0 items-center justify-center rounded-2xl border border-border/60 bg-card text-foreground/85 shadow-[inset_0_1px_0_rgba(255,255,255,0.85),0_8px_22px_rgba(15,23,42,0.08)] dark:border-border/60 dark:bg-muted/30 dark:text-foreground'
  const totalRows = items.reduce((sum, item) => sum + (Number(item.row_count) || 0), 0)
  const totalColumns = items.reduce((sum, item) => sum + (Number(item.col_count) || 0), 0)

  return (
    <AppFrame>
      <PageScaffold
        title="表格资产"
        showHeader={false}
        size="full"
        density="system-dense"
        bodyGutter="dense"
        bodyClassName="h-full overflow-hidden bg-[radial-gradient(circle_at_16%_0%,hsl(var(--info)/0.12),transparent_30%),radial-gradient(circle_at_84%_10%,hsl(var(--foreground)/0.055),transparent_28%),linear-gradient(180deg,hsl(var(--background)/0.98),hsl(var(--surface-2)/0.76))] pb-3"
        bodyContainerClassName="h-full min-h-0 overflow-hidden"
        top={
          <div className={tablesHeroCard}>
            <div className="absolute inset-y-4 left-3 w-1 rounded-full bg-[linear-gradient(180deg,hsl(var(--primary)),hsl(var(--info)/0.78),hsl(var(--primary)/0.36))]" />
            <div className="relative flex flex-col gap-3 px-5 py-3.5 pl-8 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-0 items-start gap-3.5">
                <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl border border-info/30 bg-card/82 text-primary shadow-[inset_0_1px_0_rgba(255,255,255,0.9),0_10px_26px_hsl(var(--info)/0.14)] dark:bg-info/10">
                  <Table2 className="size-5" />
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="truncate text-[22px] font-semibold leading-none tracking-[-0.035em] text-foreground dark:text-foreground">表格资产工作台</h1>
                    <span className="inline-flex h-5 items-center rounded-full border border-border bg-card/82 px-2 text-[10px] font-bold uppercase leading-none tracking-[0.12em] text-muted-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.75)] dark:border-border/60 dark:bg-muted/30 dark:text-muted-foreground">
                      table intelligence
                    </span>
                    <Badge variant="soft" className="h-5 border-primary/20 bg-primary/10 px-2 text-[10px] font-bold leading-none text-primary">
                      TAG / SQL
                    </Badge>
                  </div>
                  <div className="mt-1.5 text-[13px] leading-tight text-muted-foreground dark:text-muted-foreground">
                    <span className="font-semibold text-foreground">数据集：</span>
                    <span className="font-medium text-foreground">{dataset?.name || datasetId}</span>
                    <span> · 结构化表格资产、SQL 查询、TAG 问答与语义过滤</span>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11px] font-medium leading-none text-muted-foreground dark:text-muted-foreground">
                    <span className="inline-flex items-center gap-1.5">
                      <Database className="size-3.5 text-muted-foreground/80" />
                      <span>表格</span>
                      <span className="font-mono font-semibold text-foreground">{items.length}</span>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <BarChart3 className="size-3.5 text-muted-foreground/80" />
                      <span>总行数</span>
                      <span className="font-mono font-semibold text-foreground">{totalRows}</span>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <Cloud className="size-3.5 text-muted-foreground/80" />
                      <span>总列数</span>
                      <span className="font-mono font-semibold text-foreground">{totalColumns}</span>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <FileSearch className="size-3.5 text-muted-foreground/80" />
                      <span>当前表</span>
                      <span className="max-w-[220px] truncate font-mono font-semibold text-foreground">{selected?.table_id || '--'}</span>
                    </span>
                  </div>
                </div>
              </div>
              <div className="flex shrink-0 flex-col items-stretch gap-2 lg:w-[360px]">
                <div className="grid grid-cols-3 gap-2">
                  {[
                    ['01', '表格资产'],
                    ['02', 'SQL / TAG'],
                    ['03', '语义过滤'],
                  ].map(([step, label]) => (
                    <div key={step} className="rounded-2xl border border-border/60 bg-card/72 px-3 py-2 shadow-[0_10px_26px_rgba(15,23,42,0.07)] ring-1 ring-border/60 backdrop-blur">
                      <div className="font-mono text-[10px] font-black leading-none text-info">{step}</div>
                      <div className="mt-1 truncate text-[11px] font-bold leading-none text-foreground">{label}</div>
                    </div>
                  ))}
                </div>
                <div className="inline-flex h-9 items-center gap-2 rounded-xl border border-success/30 bg-success/5 px-3 text-[12px] font-semibold text-success shadow-[inset_0_1px_0_rgba(255,255,255,0.75),0_10px_24px_rgba(5,150,105,0.10)]">
                  <span className="size-2 rounded-full bg-success" />
                  {selected ? '已选择表格' : '等待表格资产'}
                </div>
              </div>
            </div>
          </div>
        }
        toolbar={
          <div className="flex w-full flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div className={tableToolbarGroupClass}>
              <Button size="sm" variant="ghost" className={tableToolbarButtonClass} onClick={() => router.push('/datasets')}>
                <ArrowLeft className="size-3.5" />
                返回
              </Button>
              <Button size="sm" variant="ghost" className={tableToolbarButtonClass} onClick={() => router.push(`/datasets/${datasetId}/health`)}>
                <Sparkles className="size-3.5" />
                健康
              </Button>
              <Button size="sm" variant="ghost" className={tableToolbarButtonClass} onClick={() => router.push(`/datasets/${datasetId}/profile`)}>
                <BarChart3 className="size-3.5" />
                数据画像
              </Button>
              <Button size="sm" variant="ghost" className={tableToolbarButtonClass} onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                <Database className="size-3.5" />
                入库策略
              </Button>
            </div>
          </div>
        }
      >
        <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
          <div className="grid shrink-0 grid-cols-2 gap-3 md:grid-cols-4">
            {[
              { icon: Table2, label: '表格资产', value: items.length, subValue: 'table assets', tone: 'text-info bg-info/10 border-info/20' },
              { icon: BarChart3, label: '总行数', value: totalRows, subValue: 'sum(row_count)', tone: 'text-success bg-success/10 border-success/20' },
              { icon: Database, label: '总列数', value: totalColumns, subValue: 'sum(col_count)', tone: 'text-warning bg-warning/10 border-warning/20' },
              { icon: FileSearch, label: '当前表', value: selected?.sheet_name || selected?.table_id || '—', subValue: selected ? 'selected table' : 'waiting asset', tone: 'text-success bg-success/10 border-success/20' },
            ].map((item) => (
              <div key={item.label} className={tableMetricCardClass}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-muted-foreground/70 dark:text-muted-foreground">{item.label}</div>
                    <div className="mt-1 truncate font-mono text-[17px] font-black leading-none tracking-[-0.02em] text-foreground tabular-nums dark:text-foreground">
                      {item.value}
                    </div>
                    <div className="mt-1.5 truncate text-[11px] font-medium text-muted-foreground dark:text-muted-foreground">{item.subValue}</div>
                  </div>
                  <div className={cn('flex size-8 shrink-0 items-center justify-center rounded-xl border', item.tone)}>
                    <item.icon className="size-4" />
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-hidden xl:grid-cols-[340px_minmax(0,1fr)]">
          <Panel className={cn(tablePanelClass, 'flex min-h-0 flex-col')}>
            <div className={cn(tablePanelHeaderClass, 'flex items-center justify-between gap-3')}>
              <div className="flex min-w-0 items-start gap-3">
                <div className={tableIconPillClass}>
                  <Table2 className="size-4" />
                </div>
                <div className="min-w-0">
                  <div className="mb-1 font-mono text-[10px] font-black uppercase tracking-[0.18em] text-info">Table assets</div>
                  <div className="flex items-center gap-2">
                    <div className={sectionTitleClass}>表格资产</div>
                    <Badge variant="outline" className="h-5 rounded-full px-2 font-mono text-[10px] uppercase text-muted-foreground">
                      {items.length} tables
                    </Badge>
                  </div>
                  <div className={cn(mutedHintClass, 'mt-1')}>从入库结果中提取的结构化 sheet / table</div>
                </div>
              </div>
            </div>

            <div className={cn('min-h-0 flex-1 bg-[linear-gradient(180deg,rgba(248,250,252,0.72),rgba(255,255,255,0.92))] p-4 pr-3 dark:bg-none dark:bg-muted/5', items.length ? 'space-y-2 overflow-auto no-scrollbar' : '')}>
              {items.length === 0 && !isLoading ? (
                <div className="rounded-[22px] border border-dashed border-info/30 bg-card/72 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]">
                  <div className="flex items-start gap-3">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-2xl bg-info/10 text-info">
                      <Table2 className="size-5" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-[13px] font-bold text-foreground">暂无表格资产</div>
                      <div className={cn(mutedHintClass, 'mt-1')}>
                        需要在入库策略中开启表格存储，或对包含表格的文件重新入库后再查看。
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        className="mt-3 h-8 rounded-xl bg-card px-2.5 text-[11px] font-semibold"
                        onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}
                      >
                        检查入库策略
                      </Button>
                    </div>
                  </div>
                </div>
              ) : null}

              {items.map((t) => {
                const active = selected?.table_id === t.table_id
                return (
                  <button
                    key={t.table_id}
                    type="button"
                    onClick={() => selectTable(t)}
                    className={cn(
                      'group relative w-full overflow-hidden rounded-[18px] border px-3 py-3 text-left transition-all duration-200',
                      active
                        ? 'border-info/40 bg-info/5 shadow-[0_14px_30px_hsl(var(--info)/0.14)]'
                        : 'border-border/60 bg-card/78 hover:border-info/30 hover:bg-info/5 dark:bg-card/35'
                    )}
                  >
                    {active ? <div className="absolute inset-y-3 left-0 w-1 rounded-r-full bg-[linear-gradient(180deg,hsl(var(--primary)),hsl(var(--info)/0.78),hsl(var(--success)/0.76))]" /> : null}
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate font-mono text-[11px] font-semibold text-foreground dark:text-foreground">
                          {t.sheet_name || t.table_id}
                        </div>
                        {t.sheet_name ? (
                          <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground/60">{t.table_id}</div>
                        ) : null}
                      </div>
                      <span className={cn('size-2 shrink-0 rounded-full', active ? 'bg-info' : 'bg-border group-hover:bg-info/30')} />
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
                      <span className="rounded-md bg-muted/60 px-1.5 py-0.5 dark:bg-muted/30">rows {t.row_count}</span>
                      <span className="rounded-md bg-muted/60 px-1.5 py-0.5 dark:bg-muted/30">cols {t.col_count}</span>
                    </div>
                    {t.document_filename ? (
                      <div className="mt-1.5 truncate text-[10px] text-muted-foreground/60" title={t.document_filename}>
                        {t.document_filename}
                      </div>
                    ) : null}
                  </button>
                )
              })}
            </div>
          </Panel>

          <div className="min-h-0 space-y-3 overflow-y-auto pr-1 no-scrollbar">
            {!selected ? (
              <Panel className={cn(tablePanelClass, 'min-h-[360px] p-4')}>
                <div className="flex min-h-[330px] flex-col items-center justify-center rounded-[24px] border border-dashed border-info/30 bg-[radial-gradient(circle_at_50%_0%,hsl(var(--info)/0.14),transparent_38%),linear-gradient(180deg,hsl(var(--card)/0.82),hsl(var(--background)/0.62))] p-7 text-center">
                  <div className="flex size-14 items-center justify-center rounded-[22px] border border-info/20 bg-card/86 text-info shadow-[0_14px_30px_hsl(var(--info)/0.12)]">
                    <Table2 className="size-6" />
                  </div>
                  <div className="mt-4 text-[18px] font-bold tracking-[-0.02em] text-foreground">
                    {isLoading ? '正在加载表格资产' : '选择表格后开始分析'}
                  </div>
                  <div className="mt-2 max-w-xl text-[13px] leading-6 text-muted-foreground">
                    表格工作台只在存在 table asset 时展示 SQL 查询、TAG 问答和语义过滤，避免空数据时误操作。
                  </div>
                  <div className="mt-5 grid w-full max-w-2xl grid-cols-1 gap-2 md:grid-cols-3">
                    {[
                      ['SQL', '只读 SELECT / WITH 查询'],
                      ['TAG', '自然语言转 SQL 并执行'],
                      ['语义过滤', 'LOTUS 或 fallback NL→SQL'],
                    ].map(([name, desc]) => (
                      <div key={name} className="rounded-2xl border border-border/60 bg-card/72 px-4 py-3 text-left shadow-[0_10px_24px_rgba(15,23,42,0.055)]">
                        <div className="text-[13px] font-bold text-foreground">{name}</div>
                        <div className="mt-1 text-[11px] leading-4 text-muted-foreground">{desc}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </Panel>
            ) : (
              <>
                <Panel className={cn(tablePanelClass, 'p-4')}>
                  <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                    <div>
                      <div className={sectionTitleClass}>表格信息</div>
                      <div className={cn(mutedHintClass, 'mt-0.5')}>字段结构、样例行和当前 table scope</div>
                    </div>
                    {selectedSummary}
                  </div>

                  <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(220px,0.45fr)_minmax(0,0.55fr)]">
                    <div>
                      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/60">Columns</div>
                      <div className="max-h-[180px] overflow-auto rounded-xl border border-border/50 bg-card/45 p-2 dark:bg-card/35">
                        {(selected.columns || []).length === 0 ? (
                          <div className="text-[11px] text-muted-foreground/60">未加载列信息</div>
                        ) : (
                          <div className="divide-y divide-border/40">
                            {(selected.columns || []).map((c) => (
                              <div key={c.name} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 py-1.5 font-mono text-[11px]">
                                <span className="truncate text-foreground dark:text-foreground">{c.name}</span>
                                <span className="truncate rounded-md bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground dark:bg-muted/30">{c.dtype || 'unknown'}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>

                    <div>
                      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/60">Sample Rows</div>
                      <div className="max-h-[180px] overflow-auto rounded-xl border border-border/50 bg-foreground/[0.025] p-2 dark:bg-muted/20">
                        {(selected.sample_rows || []).length === 0 ? (
                          <div className="text-[11px] text-muted-foreground/60">未加载样例，或已关闭 sample_rows</div>
                        ) : (
                          <pre className="text-[11px] font-mono leading-4 whitespace-pre-wrap break-words text-foreground/85 dark:text-muted-foreground">{JSON.stringify(selected.sample_rows || [], null, 2)}</pre>
                        )}
                      </div>
                    </div>
                  </div>
                </Panel>

                <div className="grid grid-cols-1 gap-3 2xl:grid-cols-[minmax(0,1.08fr)_minmax(360px,0.92fr)]">
                  <Panel className={cn(tablePanelClass, 'p-4')}>
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className={sectionTitleClass}>SQL 查询</div>
                        <div className={mutedHintClass}>只读查询当前表，适合快速核对字段和样例数据</div>
                      </div>
                      <Button size="sm" className="h-8 gap-1.5 rounded-lg px-2.5 text-[11px]" onClick={runQuery} disabled={queryRunning}>
                        <Play className={cn('size-3.5', queryRunning && 'animate-spin motion-reduce:animate-none')} />
                        执行
                      </Button>
                    </div>
                    <div className="mt-3 space-y-2">
                      <Textarea value={querySql} onChange={(e) => setQuerySql(e.target.value)} className="min-h-[112px] rounded-xl bg-foreground/[0.025] font-mono text-[12px] leading-5" />
                      {queryRes ? (
                        <div className="rounded-xl border border-border/55 bg-card/45 p-2 dark:bg-card/35">
                          <div className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
                            <span>cols:{(queryRes.columns || []).length}</span>
                            <span>rows:{(queryRes.rows || []).length}</span>
                            {queryRes.truncated ? <Badge variant="soft" className="h-5 px-1.5 font-mono text-[10px]">truncated</Badge> : null}
                          </div>
                          <div className="mt-2 overflow-auto">
                            <table aria-label="数据表查询结果" className="min-w-full text-[11px]">
                              <thead>
                                <tr className="border-b border-border/60 bg-muted/40 dark:bg-muted/20">
                                  {(queryRes.columns || []).map((c) => (
                                    <th key={c} className="px-2 py-1.5 text-left font-mono font-semibold whitespace-nowrap">
                                      {c}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {(queryRes.rows || []).map((r, i) => (
                                  <tr key={`query-row-${i}`} className="border-b border-border/35">
                                    {(r || []).map((v, j) => (
                                      <td key={`query-cell-${i}-${j}`} className="px-2 py-1.5 font-mono whitespace-nowrap">
                                        {renderValue(v)}
                                      </td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </Panel>

                  <div className="space-y-3">
                    <Panel className={cn(tablePanelClass, 'p-4')}>
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="flex items-center gap-1.5">
                            <Sparkles className="size-3.5 text-primary" />
                            <div className={sectionTitleClass}>TAG 问答</div>
                          </div>
                          <div className={mutedHintClass}>NL→SQL→执行</div>
                        </div>
                        <Button size="sm" className="h-8 gap-1.5 rounded-lg px-2.5 text-[11px]" onClick={ask} disabled={askRunning || !question.trim()}>
                          <Sparkles className={cn('size-3.5', askRunning && 'animate-spin motion-reduce:animate-none')} />
                          询问
                        </Button>
                      </div>
                      <div className="mt-3 space-y-2">
                        <Input value={question} onChange={(e) => setQuestion(e.target.value)} className="h-9 text-[12px]" placeholder="例如：按地区汇总销售额 TOP 10？" />
                        <div className="min-h-[38px] rounded-xl border border-border/55 bg-card/45 p-2.5 text-[12px] leading-5 dark:bg-card/35">
                          {askRes?.answer ? askRes.answer : <span className="text-[11px] text-muted-foreground/60">需要开启 TABLE_NL2SQL_ENABLED</span>}
                        </div>
                        {askRes?.sql ? (
                          <pre className="max-h-[140px] overflow-auto rounded-xl border border-border/55 bg-foreground/[0.025] p-2 text-[11px] font-mono leading-4 whitespace-pre-wrap break-words text-foreground/85 dark:bg-muted/20 dark:text-muted-foreground">{askRes.sql}</pre>
                        ) : null}
                      </div>
                    </Panel>

                    <Panel className={cn(tablePanelClass, 'p-4')}>
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className={sectionTitleClass}>语义过滤</div>
                          <div className={mutedHintClass}>LOTUS / fallback NL→SQL</div>
                        </div>
                        <Button size="sm" className="h-8 gap-1.5 rounded-lg px-2.5 text-[11px]" onClick={semFilter} disabled={semFilterRunning || !semFilterInstruction.trim()}>
                          <Play className={cn('size-3.5', semFilterRunning && 'animate-spin motion-reduce:animate-none')} />
                          运行
                        </Button>
                      </div>
                      <div className="mt-3 space-y-2">
                        <Input
                          value={semFilterInstruction}
                          onChange={(e) => setSemFilterInstruction(e.target.value)}
                          className="h-9 text-[12px]"
                          placeholder='例如："{客户名称} 是互联网公司"'
                        />
                        {semFilterRes ? (
                          <div className="rounded-xl border border-border/55 bg-card/45 p-2 dark:bg-card/35">
                            <div className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
                              <span>cols:{(semFilterRes.columns || []).length}</span>
                              <span>rows:{(semFilterRes.rows || []).length}</span>
                              {semFilterRes.truncated ? <Badge variant="soft" className="h-5 px-1.5 font-mono text-[10px]">truncated</Badge> : null}
                            </div>
                            <div className="mt-2 overflow-auto">
                              <table aria-label="数据表问答引用结果" className="min-w-full text-[11px]">
                                <thead>
                                  <tr className="border-b border-border/60 bg-muted/40 dark:bg-muted/20">
                                    {(semFilterRes.columns || []).map((c) => (
                                      <th key={c} className="px-2 py-1.5 text-left font-mono font-semibold whitespace-nowrap">
                                        {c}
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody>
                                  {(semFilterRes.rows || []).map((r, i) => (
                                    <tr key={`sem-row-${i}`} className="border-b border-border/35">
                                      {(r || []).map((v, j) => (
                                        <td key={`sem-cell-${i}-${j}`} className="px-2 py-1.5 font-mono whitespace-nowrap">
                                          {renderValue(v)}
                                        </td>
                                      ))}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        ) : null}
                      </div>
                    </Panel>
                  </div>
                </div>
              </>
            )}
          </div>
          </div>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
