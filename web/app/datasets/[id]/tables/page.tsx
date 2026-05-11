'use client'

import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, Database, Play, RefreshCw, Sparkles, Table2 } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useRouter } from '@/i18n/navigation'
import { formatApiError } from '@/lib/api-errors'
import { datasetApi } from '@/lib/api'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

import type { Dataset, DatasetTableAsset, TableAskResponse, TableQueryResponse } from '@/types'

function asDatasetId(raw: unknown): string | null {
  if (typeof raw === 'string' && raw.trim()) return raw
  if (Array.isArray(raw) && typeof raw[0] === 'string') return raw[0]
  return null
}

function renderValue(v: any): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

const TABLE_ASSET_LIST_PARAMS = { skip: 0, limit: 200 } as const

export default function DatasetTablesPage() {
  const router = useRouter()
  const params = useParams()
  const datasetId = asDatasetId((params as any)?.id)

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
    } catch (e: any) {
      console.error('Failed to load table detail', e)
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
    } catch (e: any) {
      console.error('Query failed', e)
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
    } catch (e: any) {
      console.error('Ask failed', e)
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
    } catch (e: any) {
      console.error('Sem filter failed', e)
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

  return (
    <AppFrame>
      <PageScaffold
        title="表格 / TAG"
        badge="Tables"
        icon={Table2}
        iconColor="text-teal"
        description={
          <span className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-primary/50 animate-pulse motion-reduce:animate-none" />
            {dataset ? (
              <span className="font-mono text-xs">
                Dataset: <span className="text-foreground font-semibold">{dataset.name}</span>
              </span>
            ) : (
              <span className="font-mono text-xs">Dataset Tables</span>
            )}
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/precheck`)}>
              <Database className="w-4 h-4" />
              预检
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}>
              <Database className="w-4 h-4" />
              入库策略
            </Button>
            <Button
              variant="outline"
              className="gap-2"
              onClick={() => {
                void datasetQuery.refetch()
                void tablesQuery.refetch()
              }}
              disabled={isLoading}
            >
              <RefreshCw className={cn('w-4 h-4', isLoading && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
            <Button variant="ghost" className="gap-2" onClick={() => router.push('/datasets')}>
              <ArrowLeft className="w-4 h-4" />
              返回
            </Button>
          </div>
        }
      >
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 p-6 overflow-auto">
          <Panel className="lg:col-span-1 p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="font-semibold">表格列表</div>
              <Badge variant="soft" className="font-mono text-[11px]">
                {items.length} tables
              </Badge>
            </div>
            <div className="mt-3 space-y-2 max-h-[70vh] overflow-auto pr-1">
              {items.length === 0 && !isLoading ? (
                <div className="text-sm text-muted-foreground">暂无表格（需要启用 table_store_enabled 入库）</div>
              ) : null}
              {items.map((t) => {
                const active = selected?.table_id === t.table_id
                return (
                  <button
                    key={t.table_id}
                    type="button"
                    onClick={() => selectTable(t)}
                    className={cn(
                      'w-full text-left rounded-xl border p-3 transition-colors',
                      active ? 'border-primary/60 bg-primary/5' : 'border-border/60 hover:bg-muted/20'
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-mono text-xs truncate">{t.table_id}</div>
                      {t.sheet_name ? (
                        <Badge variant="outline" className="font-mono text-[11px]">
                          {t.sheet_name}
                        </Badge>
                      ) : null}
                    </div>
                    <div className="mt-2 flex items-center gap-2 text-[11px] text-muted-foreground font-mono">
                      <span>rows:{t.row_count}</span>
                      <span>cols:{t.col_count}</span>
                      {t.document_filename ? <span className="truncate">doc:{t.document_filename}</span> : null}
                    </div>
                  </button>
                )
              })}
            </div>
          </Panel>

          <div className="lg:col-span-2 space-y-6">
            <Panel className="p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="font-semibold">表格信息</div>
                {selectedSummary}
              </div>
              <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <div className="text-xs text-muted-foreground mb-2">Columns</div>
                  <div className="max-h-[220px] overflow-auto rounded-lg border border-border/60 p-2">
                    {(selected?.columns || []).length === 0 ? (
                      <div className="text-xs text-muted-foreground">（未加载列信息）</div>
                    ) : (
                      <div className="space-y-1">
                        {(selected?.columns || []).map((c) => (
                          <div key={c.name} className="flex items-center justify-between gap-2 text-xs font-mono">
                            <span className="truncate">{c.name}</span>
                            <span className="text-muted-foreground truncate">{c.dtype || ''}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                <div>
                  <div className="text-xs text-muted-foreground mb-2">Sample Rows</div>
                  <div className="max-h-[220px] overflow-auto rounded-lg border border-border/60 p-2">
                    {(selected?.sample_rows || []).length === 0 ? (
                      <div className="text-xs text-muted-foreground">（未加载样例 / 或已关闭 sample_rows）</div>
                    ) : (
                      <pre className="text-xs font-mono whitespace-pre-wrap break-words">{JSON.stringify(selected?.sample_rows || [], null, 2)}</pre>
                    )}
                  </div>
                </div>
              </div>
            </Panel>

            <Panel className="p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="font-semibold">SQL 查询</div>
                <Button size="sm" className="gap-2" onClick={runQuery} disabled={!selected || queryRunning}>
                  <Play className={cn('w-4 h-4', queryRunning && 'animate-spin motion-reduce:animate-none')} />
                  执行
                </Button>
              </div>
              <div className="mt-3 space-y-2">
                <Textarea value={querySql} onChange={(e) => setQuerySql(e.target.value)} className="min-h-[140px] font-mono text-xs" />
                {queryRes ? (
                  <div className="rounded-lg border border-border/60 p-3">
                    <div className="flex items-center gap-2 text-xs font-mono text-muted-foreground">
                      <span>cols:{(queryRes.columns || []).length}</span>
                      <span>rows:{(queryRes.rows || []).length}</span>
                      {queryRes.truncated ? <Badge variant="soft" className="font-mono text-[11px]">truncated</Badge> : null}
                    </div>
                    <div className="mt-2 overflow-auto">
                      <table aria-label="数据表查询结果" className="min-w-full text-xs">
                        <thead>
                          <tr className="border-b border-border/60">
                            {(queryRes.columns || []).map((c) => (
                              <th key={c} className="text-left font-mono py-2 pr-3 whitespace-nowrap">
                                {c}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {(queryRes.rows || []).map((r) => (
                            <tr key={JSON.stringify(r)} className="border-b border-border/40">
                              {(r || []).map((v, j) => (
                                <td key={String(queryRes.columns?.[j] ?? v)} className="py-1.5 pr-3 font-mono whitespace-nowrap">
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

            <Panel className="p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="font-semibold flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-primary" />
                  TAG 问答（NL→SQL→执行）
                </div>
                <Button size="sm" className="gap-2" onClick={ask} disabled={!selected || askRunning || !question.trim()}>
                  <Sparkles className={cn('w-4 h-4', askRunning && 'animate-spin motion-reduce:animate-none')} />
                  询问
                </Button>
              </div>
              <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>问题</Label>
                  <Input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="例如：按地区汇总销售额 TOP 10？" />
                </div>
                <div className="space-y-2">
                  <Label>回答</Label>
                  <div className="min-h-[44px] rounded-lg border border-border/60 p-3 text-sm">
                    {askRes?.answer ? askRes.answer : <span className="text-muted-foreground">（需要开启 TABLE_NL2SQL_ENABLED）</span>}
                  </div>
                </div>
              </div>
              {askRes?.sql ? (
                <div className="mt-3 rounded-lg border border-border/60 p-3">
                  <div className="text-xs text-muted-foreground font-mono mb-2">SQL</div>
                  <pre className="text-xs font-mono whitespace-pre-wrap break-words">{askRes.sql}</pre>
                </div>
              ) : null}
            </Panel>

            <Panel className="p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="font-semibold">语义过滤（LOTUS / fallback NL→SQL）</div>
                <Button size="sm" className="gap-2" onClick={semFilter} disabled={!selected || semFilterRunning || !semFilterInstruction.trim()}>
                  <Play className={cn('w-4 h-4', semFilterRunning && 'animate-spin motion-reduce:animate-none')} />
                  运行
                </Button>
              </div>
              <div className="mt-3 space-y-2">
                <Input
                  value={semFilterInstruction}
                  onChange={(e) => setSemFilterInstruction(e.target.value)}
                  placeholder='例如："{客户名称} 是互联网公司"（LOTUS 语法）'
                />
                {semFilterRes ? (
                  <div className="rounded-lg border border-border/60 p-3">
                    <div className="flex items-center gap-2 text-xs font-mono text-muted-foreground">
                      <span>cols:{(semFilterRes.columns || []).length}</span>
                      <span>rows:{(semFilterRes.rows || []).length}</span>
                      {semFilterRes.truncated ? <Badge variant="soft" className="font-mono text-[11px]">truncated</Badge> : null}
                    </div>
                    <div className="mt-2 overflow-auto">
                      <table aria-label="数据表问答引用结果" className="min-w-full text-xs">
                        <thead>
                          <tr className="border-b border-border/60">
                            {(semFilterRes.columns || []).map((c) => (
                              <th key={c} className="text-left font-mono py-2 pr-3 whitespace-nowrap">
                                {c}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {(semFilterRes.rows || []).map((r) => (
                            <tr key={JSON.stringify(r)} className="border-b border-border/40">
                              {(r || []).map((v, j) => (
                                <td key={String(semFilterRes.columns?.[j] ?? v)} className="py-1.5 pr-3 font-mono whitespace-nowrap">
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
      </PageScaffold>
    </AppFrame>
  )
}
