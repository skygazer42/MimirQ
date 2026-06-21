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

  const tablesHeroCard = 'relative overflow-hidden rounded-2xl border border-white/70 bg-[linear-gradient(135deg,rgba(255,255,255,0.98),rgba(240,249,255,0.88)_58%,rgba(236,253,245,0.62))] shadow-[0_18px_50px_rgba(15,23,42,0.08)] ring-1 ring-sky-100/70 before:pointer-events-none before:absolute before:inset-0 before:bg-[radial-gradient(circle_at_18%_12%,rgba(14,165,233,0.14),transparent_28%),linear-gradient(90deg,rgba(14,165,233,0.035)_1px,transparent_1px),linear-gradient(0deg,rgba(14,165,233,0.035)_1px,transparent_1px)] before:bg-[length:auto,28px_28px,28px_28px] dark:border-border/60 dark:bg-card/95 dark:ring-sky-500/15'
  const tablePanelClass = 'overflow-hidden border-white/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,250,252,0.92))] p-3 shadow-[0_16px_45px_rgba(15,23,42,0.07)] ring-1 ring-slate-100/70 dark:border-border/60 dark:bg-card/95 dark:ring-white/5'
  const sectionTitleClass = 'text-[13px] font-semibold tracking-[-0.01em] text-slate-900 dark:text-foreground'
  const mutedHintClass = 'text-[11px] leading-4 text-muted-foreground/65'
  const tableToolbarGroupClass = 'inline-flex flex-wrap items-center gap-1 rounded-2xl border border-white/70 bg-white/70 p-1 shadow-[0_10px_30px_rgba(15,23,42,0.055)] ring-1 ring-slate-100/70 backdrop-blur dark:border-border/60 dark:bg-card/70 dark:ring-white/5'
  const tableToolbarButtonClass = 'h-8 gap-1.5 rounded-xl px-2.5 text-[12px] font-medium text-slate-600 shadow-none hover:bg-white/95 hover:text-slate-900 hover:shadow-sm dark:text-muted-foreground dark:hover:bg-muted/60 dark:hover:text-foreground [&_svg]:size-3.5'
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
        bodyClassName="h-full overflow-hidden bg-[radial-gradient(circle_at_18%_0%,rgba(14,165,233,0.10),transparent_28%),linear-gradient(180deg,rgba(248,250,252,0.96),rgba(241,245,249,0.68))] pb-3 dark:bg-[radial-gradient(circle_at_18%_0%,rgba(14,165,233,0.14),transparent_28%),linear-gradient(180deg,rgba(15,23,42,0.96),rgba(15,23,42,0.86))]"
        bodyContainerClassName="h-full min-h-0 overflow-hidden"
        top={
          <div className={tablesHeroCard}>
            <div className="absolute inset-y-4 left-3 w-1 rounded-full bg-gradient-to-b from-primary via-sky-400 to-cyan-300" />
            <div className="relative flex flex-col gap-3 px-5 py-3.5 pl-8 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-0 items-start gap-3.5">
                <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl border border-sky-200/80 bg-white/82 text-primary shadow-[inset_0_1px_0_rgba(255,255,255,0.9),0_10px_26px_rgba(14,165,233,0.14)] dark:border-sky-500/25 dark:bg-sky-500/10">
                  <Table2 className="size-5" />
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="truncate text-[20px] font-medium leading-none tracking-[-0.01em] text-slate-800 dark:text-foreground">表格资产</h1>
                    <Badge variant="soft" className="h-5 border-primary/20 bg-primary/10 px-2 text-[10px] font-medium leading-none text-primary">
                      TAG / SQL
                    </Badge>
                  </div>
                  <div className="mt-1.5 text-[13px] leading-tight text-muted-foreground">
                    <span className="font-semibold text-foreground">数据集：</span>
                    <span className="font-medium text-foreground">{dataset?.name || datasetId}</span>
                    <span> · 结构化表格资产、SQL 查询、TAG 问答与语义过滤</span>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11px] leading-none text-muted-foreground">
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
              <div className="flex shrink-0 items-center gap-2 lg:self-end">
                <div className="inline-flex h-9 items-center gap-2 rounded-lg border border-emerald-200/80 bg-emerald-50/90 px-3 text-[13px] font-medium text-emerald-700 shadow-[inset_0_1px_0_rgba(255,255,255,0.75)] dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
                  <span className="size-2 rounded-full bg-emerald-500" />
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
        <div className="grid h-full min-h-0 grid-cols-1 gap-3 overflow-hidden xl:grid-cols-[320px_minmax(0,1fr)]">
          <Panel className={cn(tablePanelClass, 'flex min-h-0 flex-col')}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className={sectionTitleClass}>表格资产</div>
                <div className={cn(mutedHintClass, 'mt-0.5')}>从入库结果中提取的结构化 sheet / table</div>
              </div>
              <Badge variant="soft" className="h-5 px-1.5 font-mono text-[10px]">
                {items.length} tables
              </Badge>
            </div>

            <div className={cn('mt-3 min-h-0 flex-1 pr-1', items.length ? 'space-y-1.5 overflow-auto no-scrollbar' : '')}>
              {items.length === 0 && !isLoading ? (
                <div className="rounded-xl border border-dashed border-sky-200/80 bg-sky-50/40 p-3">
                  <div className="flex items-center gap-2 text-[12px] font-semibold text-slate-800">
                    <Table2 className="size-4 text-sky-500" />
                    暂无表格资产
                  </div>
                  <div className={cn(mutedHintClass, 'mt-2')}>
                    需要在入库策略中开启表格存储，或对包含表格的文件重新入库后再查看。
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-3 h-8 rounded-lg px-2.5 text-[11px]"
                    onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}
                  >
                    检查入库策略
                  </Button>
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
                      'group w-full rounded-xl border px-2.5 py-2 text-left transition-all duration-200',
                      active
                        ? 'border-sky-300 bg-sky-50/75 shadow-[0_10px_26px_rgba(14,165,233,0.10)]'
                        : 'border-border/55 bg-white/45 hover:border-sky-200 hover:bg-sky-50/45 dark:bg-card/35'
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate font-mono text-[11px] font-semibold text-slate-800 dark:text-foreground">
                          {t.sheet_name || t.table_id}
                        </div>
                        {t.sheet_name ? (
                          <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground/60">{t.table_id}</div>
                        ) : null}
                      </div>
                      <span className={cn('size-2 shrink-0 rounded-full', active ? 'bg-sky-500' : 'bg-slate-300 group-hover:bg-sky-300')} />
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
                      <span className="rounded-md bg-slate-100/75 px-1.5 py-0.5 dark:bg-muted/30">rows {t.row_count}</span>
                      <span className="rounded-md bg-slate-100/75 px-1.5 py-0.5 dark:bg-muted/30">cols {t.col_count}</span>
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
              <Panel className={cn(tablePanelClass, 'min-h-[300px]')}>
                <div className="flex min-h-[270px] flex-col items-center justify-center rounded-2xl border border-dashed border-sky-200/80 bg-[radial-gradient(circle_at_50%_0%,rgba(14,165,233,0.10),transparent_38%),linear-gradient(180deg,rgba(255,255,255,0.76),rgba(248,250,252,0.58))] p-6 text-center">
                  <div className="flex size-12 items-center justify-center rounded-2xl border border-sky-100 bg-white/80 text-sky-500 shadow-sm">
                    <Table2 className="size-5" />
                  </div>
                  <div className="mt-3 text-[15px] font-semibold text-slate-900">
                    {isLoading ? '正在加载表格资产' : '选择表格后开始分析'}
                  </div>
                  <div className="mt-1 max-w-xl text-[12px] leading-5 text-muted-foreground/70">
                    表格工作台只在存在 table asset 时展示 SQL 查询、TAG 问答和语义过滤，避免空数据时误操作。
                  </div>
                  <div className="mt-4 grid w-full max-w-2xl grid-cols-1 gap-2 md:grid-cols-3">
                    {[
                      ['SQL', '只读 SELECT / WITH 查询'],
                      ['TAG', '自然语言转 SQL 并执行'],
                      ['语义过滤', 'LOTUS 或 fallback NL→SQL'],
                    ].map(([name, desc]) => (
                      <div key={name} className="rounded-xl border border-white/70 bg-white/65 px-3 py-2 text-left shadow-sm">
                        <div className="text-[12px] font-semibold text-slate-800">{name}</div>
                        <div className="mt-0.5 text-[10px] leading-4 text-muted-foreground/60">{desc}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </Panel>
            ) : (
              <>
                <Panel className={tablePanelClass}>
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
                      <div className="max-h-[180px] overflow-auto rounded-xl border border-border/50 bg-white/45 p-2 dark:bg-card/35">
                        {(selected.columns || []).length === 0 ? (
                          <div className="text-[11px] text-muted-foreground/60">未加载列信息</div>
                        ) : (
                          <div className="divide-y divide-border/40">
                            {(selected.columns || []).map((c) => (
                              <div key={c.name} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 py-1.5 font-mono text-[11px]">
                                <span className="truncate text-slate-800 dark:text-foreground">{c.name}</span>
                                <span className="truncate rounded-md bg-slate-100/75 px-1.5 py-0.5 text-[10px] text-muted-foreground dark:bg-muted/30">{c.dtype || 'unknown'}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>

                    <div>
                      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/60">Sample Rows</div>
                      <div className="max-h-[180px] overflow-auto rounded-xl border border-border/50 bg-slate-950/[0.025] p-2 dark:bg-muted/20">
                        {(selected.sample_rows || []).length === 0 ? (
                          <div className="text-[11px] text-muted-foreground/60">未加载样例，或已关闭 sample_rows</div>
                        ) : (
                          <pre className="text-[11px] font-mono leading-4 whitespace-pre-wrap break-words text-slate-700 dark:text-muted-foreground">{JSON.stringify(selected.sample_rows || [], null, 2)}</pre>
                        )}
                      </div>
                    </div>
                  </div>
                </Panel>

                <div className="grid grid-cols-1 gap-3 2xl:grid-cols-[minmax(0,1.08fr)_minmax(360px,0.92fr)]">
                  <Panel className={tablePanelClass}>
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
                      <Textarea value={querySql} onChange={(e) => setQuerySql(e.target.value)} className="min-h-[112px] rounded-xl bg-slate-950/[0.025] font-mono text-[12px] leading-5" />
                      {queryRes ? (
                        <div className="rounded-xl border border-border/55 bg-white/45 p-2 dark:bg-card/35">
                          <div className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
                            <span>cols:{(queryRes.columns || []).length}</span>
                            <span>rows:{(queryRes.rows || []).length}</span>
                            {queryRes.truncated ? <Badge variant="soft" className="h-5 px-1.5 font-mono text-[10px]">truncated</Badge> : null}
                          </div>
                          <div className="mt-2 overflow-auto">
                            <table aria-label="数据表查询结果" className="min-w-full text-[11px]">
                              <thead>
                                <tr className="border-b border-border/60 bg-slate-50/70 dark:bg-muted/20">
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
                    <Panel className={tablePanelClass}>
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
                        <div className="min-h-[38px] rounded-xl border border-border/55 bg-white/45 p-2.5 text-[12px] leading-5 dark:bg-card/35">
                          {askRes?.answer ? askRes.answer : <span className="text-[11px] text-muted-foreground/60">需要开启 TABLE_NL2SQL_ENABLED</span>}
                        </div>
                        {askRes?.sql ? (
                          <pre className="max-h-[140px] overflow-auto rounded-xl border border-border/55 bg-slate-950/[0.025] p-2 text-[11px] font-mono leading-4 whitespace-pre-wrap break-words text-slate-700 dark:bg-muted/20 dark:text-muted-foreground">{askRes.sql}</pre>
                        ) : null}
                      </div>
                    </Panel>

                    <Panel className={tablePanelClass}>
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
                          <div className="rounded-xl border border-border/55 bg-white/45 p-2 dark:bg-card/35">
                            <div className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
                              <span>cols:{(semFilterRes.columns || []).length}</span>
                              <span>rows:{(semFilterRes.rows || []).length}</span>
                              {semFilterRes.truncated ? <Badge variant="soft" className="h-5 px-1.5 font-mono text-[10px]">truncated</Badge> : null}
                            </div>
                            <div className="mt-2 overflow-auto">
                              <table aria-label="数据表问答引用结果" className="min-w-full text-[11px]">
                                <thead>
                                  <tr className="border-b border-border/60 bg-slate-50/70 dark:bg-muted/20">
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
      </PageScaffold>
    </AppFrame>
  )
}
