'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, BarChart3, Cloud, Database, FileSearch, Play, Sparkles, Table2 } from '@/components/icons'

import { AppFrame } from '@/components/app-frame'
import { OperationalWorkspace, DirectoryWorkspace, WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
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
  if (v === null) return 'NULL'
  if (v === undefined) return '—'
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    return JSON.stringify(v)
  } catch {
    return toTrimmedPrimitiveString(v)
  }
}

const TABLE_ASSET_LIST_PARAMS = { skip: 0, limit: 200 } as const

function TableResult({ result }: { result: TableQueryResponse }) {
  return <div className={ws.tableScroll}><table className={ws.table} aria-label="数据表查询结果"><thead><tr>{result.columns.map((column, index) => <th key={`${index}:${column}`}>{column}</th>)}</tr></thead><tbody>{result.rows.map((row, index) => <tr key={index}>{row.map((value, position) => <td key={position}>{renderValue(value)}</td>)}</tr>)}</tbody></table>{!result.rows.length ? <p className="py-4 text-sm text-muted-foreground">查询没有返回行。</p> : null}{result.truncated ? <p className="py-3 text-sm text-muted-foreground">结果已按返回上限截取。</p> : null}</div>
}

export default function DatasetTablesPage() {
  const router = useRouter()
  const params = useParams()
  const datasetId = asDatasetId((params as Record<string, unknown>)?.id)

  const [pane, setPane] = useState<'directory' | 'detail'>('directory')
  const tableIntent = useRef<{ datasetId: string | null; tableId: string } | null>(null)
  const [errors, setErrors] = useState<Record<'query' | 'ask' | 'filter', string | null>>({ query: null, ask: null, filter: null })
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
    reportClientError('Failed to load table assets', loadError)
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

  const detailQuery = useQuery({
    queryKey: queryKeys.datasets.tableAsset(datasetId || '', selected?.table_id || ''),
    queryFn: () => datasetApi.getTable(datasetId!, selected!.table_id, { include_columns: true, include_sample_rows: true }),
    enabled: Boolean(datasetId && selected?.table_id),
  })
  const table = detailQuery.data ?? selected
  useEffect(() => {
    if (tableIntent.current?.datasetId === datasetId && tableIntent.current?.tableId === selected?.table_id) return
    tableIntent.current = selected ? { datasetId, tableId: selected.table_id } : null
    setQueryRes(null); setAskRes(null); setSemFilterRes(null)
    setQueryRunning(false); setAskRunning(false); setSemFilterRunning(false)
    setErrors({ query: null, ask: null, filter: null })
  }, [datasetId, selected])

  const selectTable = (next: DatasetTableAsset) => {
    if (next.table_id !== selected?.table_id || tableIntent.current?.datasetId !== datasetId) {
      tableIntent.current = { datasetId, tableId: next.table_id }
      setQueryRes(null); setAskRes(null); setSemFilterRes(null)
      setQueryRunning(false); setAskRunning(false); setSemFilterRunning(false)
      setErrors({ query: null, ask: null, filter: null })
      setQuerySql(`SELECT * FROM "sheet_${next.sheet_index}" LIMIT 20`)
    }
    setSelected(next); setPane('detail')
  }

  const runQuery = async () => {
    if (!datasetId || !selected) return
    const intent = tableIntent.current
    setErrors(current => ({ ...current, query: null }))
    setQueryRunning(true)
    setQueryRes(null)
    try {
      const res = await datasetApi.queryTable(datasetId, selected.table_id, { sql: querySql })
      if (tableIntent.current === intent) setQueryRes(res)
    } catch (e: unknown) {
      reportClientError('Dataset table SQL query failed', e)
      if (tableIntent.current === intent) setErrors(current => ({ ...current, query: formatApiError(e, '查询失败，只支持只读 SQL。') }))
    } finally {
      if (tableIntent.current === intent) setQueryRunning(false)
    }
  }

  const ask = async () => {
    if (!datasetId || !selected) return
    if (!question.trim()) return
    const intent = tableIntent.current
    setErrors(current => ({ ...current, ask: null }))
    setAskRunning(true)
    setAskRes(null)
    try {
      const res = await datasetApi.askTable(datasetId, selected.table_id, { question: question.trim() })
      if (tableIntent.current === intent) setAskRes(res)
    } catch (e: unknown) {
      reportClientError('Dataset table question answering failed', e)
      if (tableIntent.current === intent) setErrors(current => ({ ...current, ask: formatApiError(e, '问答失败') }))
    } finally {
      if (tableIntent.current === intent) setAskRunning(false)
    }
  }

  const semFilter = async () => {
    if (!datasetId || !selected) return
    if (!semFilterInstruction.trim()) return
    const intent = tableIntent.current
    setErrors(current => ({ ...current, filter: null }))
    setSemFilterRunning(true)
    setSemFilterRes(null)
    try {
      const res = await datasetApi.lotusSemFilter(datasetId, selected.table_id, { user_instruction: semFilterInstruction.trim(), strategy: 'cot' })
      if (tableIntent.current === intent) setSemFilterRes(res)
    } catch (e: unknown) {
      reportClientError('Dataset table semantic filter failed', e)
      if (tableIntent.current === intent) setErrors(current => ({ ...current, filter: formatApiError(e, '语义过滤失败') }))
    } finally {
      if (tableIntent.current === intent) setSemFilterRunning(false)
    }
  }

  return <AppFrame><OperationalWorkspace title="表格资产" icon="dataset" mode="canvas" context={dataset?.name ?? '正在读取数据集…'} back={() => router.push('/datasets')} actions={<Button variant="outline" onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}>入库策略</Button>}>
    {loadError ? <div className="px-5"><WorkspaceNotice retry={() => { void datasetQuery.refetch(); void tablesQuery.refetch() }} pending={isLoading}>{formatApiError(loadError, '表格读取失败')}</WorkspaceNotice></div> : null}
    <DirectoryWorkspace pane={pane} onPaneChange={setPane} directoryLabel="表格目录" detailLabel="当前表格" directory={<><div className={ws.directoryHeader}><h2 className={ws.sectionTitle}>表格目录</h2><p className={ws.muted}>{tablesQuery.isPending ? '正在读取…' : tablesQuery.isError ? '目录读取失败' : `${items.length} 张表`}</p></div>{items.map(item => <button key={item.table_id} className={ws.directoryRow} data-selected={selected?.table_id === item.table_id} aria-label={`选择表 ${item.sheet_name || item.table_id}`} onClick={() => selectTable(item)}><strong title={item.sheet_name || item.table_id}>{item.sheet_name || item.table_id}</strong><small>{item.row_count} 行 · {item.col_count} 列</small>{item.document_filename ? <small>{item.document_filename}</small> : null}</button>)}{!items.length && !tablesQuery.isPending && !tablesQuery.isError ? <div className="p-4"><h3 className="text-sm font-medium">还没有表格资产</h3><p className={ws.muted}>含表格的文档入库后，可在这里查看和查询。</p><Button className="mt-3" variant="outline" onClick={() => router.push(`/knowledge/ingestion?datasetId=${datasetId}`)}>去入库操作</Button></div> : null}</>}>
      {!table ? <div className={ws.empty}><h2>{items.length ? '选择表格' : tablesQuery.isPending ? '正在读取表格目录…' : tablesQuery.isError ? '表格目录读取失败' : '还没有表格资产'}</h2><p>{items.length ? '从目录选择一张表，查看数据或发起查询。' : '含表格的文档解析入库后，可在这里查看和查询。'}</p>{!items.length && !isLoading && !loadError ? <Button variant="outline" onClick={() => router.push(`/knowledge/ingestion?datasetId=${datasetId}`)}>去入库操作</Button> : null}</div> : <><div className={ws.sectionHeading}><div><h2 className={ws.sectionTitle}>{table.sheet_name || table.table_id}</h2><p className={ws.muted}>{table.document_filename} · {table.row_count} 行 · {table.col_count} 列</p></div></div>{detailQuery.isError ? <WorkspaceNotice retry={() => { void detailQuery.refetch() }} pending={detailQuery.isFetching}>{formatApiError(detailQuery.error, '表格详情读取失败')}</WorkspaceNotice> : null}
        <Tabs defaultValue="data"><TabsList className={ws.tabList} aria-label="表格工具"><TabsTrigger value="data">数据预览</TabsTrigger><TabsTrigger value="sql">SQL 查询</TabsTrigger><TabsTrigger value="ask">表格问答</TabsTrigger><TabsTrigger value="filter">语义筛选</TabsTrigger></TabsList>
          <TabsContent value="data" className={ws.tabContent}><section className={ws.section}><h3 className={ws.sectionTitle}>字段</h3><div className={ws.tableScroll}><table className={ws.table} aria-label="表格字段"><thead><tr><th>名称</th><th>类型</th></tr></thead><tbody>{(table.columns ?? []).map(column => <tr key={column.name}><td>{column.name}</td><td>{column.dtype ?? '未返回'}</td></tr>)}</tbody></table></div></section><section className={ws.section}><h3 className={ws.sectionTitle}>样例数据</h3><div className={ws.tableScroll}><table className={ws.table} aria-label="表格样例数据"><thead><tr>{(table.columns ?? []).map(column => <th key={column.name}>{column.name}</th>)}</tr></thead><tbody>{(table.sample_rows ?? []).map((row, index) => <tr key={index}>{(table.columns ?? []).map(column => <td key={column.name}>{renderValue(row[column.name])}</td>)}</tr>)}</tbody></table>{!table.sample_rows?.length ? <p className="py-4 text-sm text-muted-foreground">{detailQuery.isFetching ? '正在读取样例…' : '未返回样例数据。'}</p> : null}</div></section></TabsContent>
          <TabsContent value="sql" className={ws.tabContent}><section className={ws.section}><Label htmlFor="table-sql">SQL 查询语句</Label><Textarea id="table-sql" value={querySql} onChange={event => setQuerySql(event.target.value)} className="my-3 min-h-32 font-mono text-sm" /><Button disabled={queryRunning || !querySql.trim()} onClick={() => { void runQuery() }}><Play />{queryRunning ? '正在查询…' : '执行查询'}</Button>{errors.query ? <WorkspaceNotice>{errors.query}</WorkspaceNotice> : null}{queryRes ? <TableResult result={queryRes} /> : null}</section></TabsContent>
          <TabsContent value="ask" className={ws.tabContent}><section className={ws.section}><Label htmlFor="table-question">向当前表格提问</Label><Input id="table-question" className="my-3" value={question} onChange={event => setQuestion(event.target.value)} placeholder="例如：按地区汇总销售额" /><Button disabled={askRunning || !question.trim()} onClick={() => { void ask() }}><Sparkles />{askRunning ? '正在查询…' : '查询表格'}</Button>{errors.ask ? <WorkspaceNotice>{errors.ask}</WorkspaceNotice> : null}{askRes ? <div className="mt-5 space-y-4 text-sm leading-7"><p>{askRes.answer}</p>{askRes.sql ? <pre className="overflow-auto bg-muted/30 p-3 text-xs">{askRes.sql}</pre> : null}{askRes.data ? <TableResult result={askRes.data} /> : null}</div> : null}</section></TabsContent>
          <TabsContent value="filter" className={ws.tabContent}><section className={ws.section}><Label htmlFor="table-sem-filter">筛选条件</Label><Input id="table-sem-filter" className="my-3" value={semFilterInstruction} onChange={event => setSemFilterInstruction(event.target.value)} placeholder="描述要保留的行" /><Button disabled={semFilterRunning || !semFilterInstruction.trim()} onClick={() => { void semFilter() }}><Play />{semFilterRunning ? '正在筛选…' : '筛选数据'}</Button>{errors.filter ? <WorkspaceNotice>{errors.filter}</WorkspaceNotice> : null}{semFilterRes ? <TableResult result={semFilterRes} /> : null}</section></TabsContent>
        </Tabs>
      </>}
    </DirectoryWorkspace>
  </OperationalWorkspace></AppFrame>
}
