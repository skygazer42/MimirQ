'use client'

import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { useParams } from 'next/navigation'
import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query'
import { Cloud, Play, Sparkles, Table2 } from '@/components/icons'

import { AppFrame } from '@/components/app-frame'
import {
  OperationalWorkspace,
  DirectoryWorkspace,
  WorkspaceNotice,
  workspaceStyles as ws,
} from '@/components/ui/operational-workspace'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Link, useRouter } from '@/i18n/navigation'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { datasetApi } from '@/lib/api'
import { reportClientError } from '@/lib/client-logging'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'

import type { DatasetTableAsset, TableQueryResponse } from '@/types'

function getTableLabel(table: DatasetTableAsset): string {
  const sheetName = table.sheet_name?.trim()
  return sheetName === undefined || sheetName === '' ? table.table_id : sheetName
}

function formatTableCell(value: unknown): string {
  if (value === null) return 'NULL'
  if (value === undefined) return '—'
  return typeof value === 'string' ? value : JSON.stringify(value)
}

const TABLE_ASSET_LIST_PARAMS = { limit: 200 } as const

function TableAssetsEmptyState({ datasetId }: Readonly<{ datasetId: string }>) {
  return (
    <section className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-5 py-10 text-center">
      <div className="my-auto w-full max-w-lg">
        <div
          aria-hidden="true"
          className="mx-auto mb-6 w-48 rounded-xl border border-border/70 bg-card p-3 shadow-subtle"
        >
          <div className="mb-2 flex items-center gap-2">
            <Table2 className="size-4 text-ring" />
            <span className="h-2 w-20 rounded bg-muted" />
          </div>
          <div className="grid grid-cols-3 gap-1.5 border-t border-border/60 pt-2">
            {Array.from({ length: 9 }, (_, index) => (
              <span key={index} className={cn('h-2 rounded', index < 3 ? 'bg-muted-foreground/25' : 'bg-muted')} />
            ))}
          </div>
        </div>
        <h2 className="text-lg font-semibold">当前数据集尚无结构化表格资产</h2>
        <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted-foreground">
          包含表格的文档完成解析入库后，可在这里查看表头、预览数据，并进行表格查询。
        </p>
        <ul
          aria-label="表格资产能力"
          className="mt-4 flex flex-wrap justify-center gap-2 text-xs text-muted-foreground"
        >
          {['结构预览', '只读 SQL', '自然语言问表'].map((label) => (
            <li key={label} className="rounded-full bg-muted/60 px-2.5 py-1">
              {label}
            </li>
          ))}
        </ul>
        <div className="mt-6 flex flex-wrap justify-center gap-2.5">
          <Button asChild className="gap-2 bg-accent text-accent-foreground hover:bg-accent/90">
            <Link href={`/knowledge/ingestion?datasetId=${encodeURIComponent(datasetId)}`}>
              <Cloud className="size-4" />
              前往入库操作
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href={`/datasets/${encodeURIComponent(datasetId)}/ingestion`}>配置入库策略</Link>
          </Button>
        </div>
      </div>
    </section>
  )
}

function TableResult({ result }: { result: TableQueryResponse }) {
  return (
    <div className={ws.tableScroll}>
      <table className={ws.table} aria-label="数据表查询结果">
        <thead>
          <tr>
            {result.columns.map((column, index) => (
              <th key={`${index}:${column}`}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, index) => (
            <tr key={index}>
              {row.map((value, position) => (
                <td key={position}>{formatTableCell(value)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!result.rows.length ? <p className="py-4 text-sm text-muted-foreground">查询没有返回行。</p> : null}
      {result.truncated ? <p className="py-3 text-sm text-muted-foreground">结果已按返回上限截取。</p> : null}
    </div>
  )
}

export default function DatasetTablesPage() {
  const { id: datasetId } = useParams<{ id: string }>()
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return (
    <AppFrame>
      <DatasetTablesWorkspace key={JSON.stringify([datasetId, sessionKey])} datasetId={datasetId} />
    </AppFrame>
  )
}

function DatasetTablesWorkspace({ datasetId }: Readonly<{ datasetId: string }>) {
  const router = useRouter()
  const [pane, setPane] = useState<'directory' | 'detail'>('directory')
  const [selectedTableId, setSelectedTableId] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [semFilterInstruction, setSemFilterInstruction] = useState('')

  const datasetQuery = useQuery({
    queryKey: queryKeys.datasets.detail(datasetId),
    queryFn: ({ signal }) => datasetApi.get(datasetId, { signal }),
  })
  const tablesQuery = useInfiniteQuery({
    queryKey: queryKeys.datasets.tables(datasetId, TABLE_ASSET_LIST_PARAMS),
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      datasetApi.listTables(datasetId, { ...TABLE_ASSET_LIST_PARAMS, skip: pageParam }, { signal }),
    getNextPageParam: (lastPage) => lastPage.next_skip,
  })
  const dataset = datasetQuery.data
  let datasetLabel = datasetQuery.isPending ? '正在读取数据集…' : datasetId
  if (dataset !== undefined) {
    datasetLabel = dataset.name.trim() === '' ? dataset.id : dataset.name
  }
  const items = useMemo(() => {
    const tables = new Map<string, DatasetTableAsset>()
    for (const page of tablesQuery.data?.pages ?? []) {
      for (const table of page.items) tables.set(table.table_id, table)
    }
    return [...tables.values()]
  }, [tablesQuery.data])
  const firstTableId = items[0]?.table_id
  const selectedTable = items.find((item) => item.table_id === (selectedTableId ?? firstTableId))
  useEffect(() => {
    if (firstTableId !== undefined) setSelectedTableId((current) => current ?? firstTableId)
  }, [firstTableId])

  const isLoading = datasetQuery.isFetching || tablesQuery.isFetching
  const loadError = datasetQuery.error ?? tablesQuery.error
  const loadErrorUpdatedAt = Math.max(datasetQuery.errorUpdatedAt, tablesQuery.errorUpdatedAt)
  const hasMoreTableDocuments = tablesQuery.hasNextPage
  const showEmptyStage = tablesQuery.isSuccess && !hasMoreTableDocuments && items.length === 0
  const scanningTableDocuments = items.length === 0 && hasMoreTableDocuments && !tablesQuery.isError
  const { fetchNextPage } = tablesQuery
  useEffect(() => {
    if (scanningTableDocuments && !tablesQuery.isFetching) void fetchNextPage({ cancelRefetch: false })
  }, [scanningTableDocuments, tablesQuery.isFetching, fetchNextPage])

  useEffect(() => {
    if (!loadError) return
    reportClientError('Failed to load table assets', loadError)
  }, [loadError, loadErrorUpdatedAt])

  return (
    <OperationalWorkspace
      title="表格资产"
      icon="table-assets"
      mode="canvas"
      context={datasetLabel}
      back={() => router.push('/datasets')}
      actions={
        <Button asChild variant="outline">
          <Link href={`/datasets/${encodeURIComponent(datasetId)}/ingestion`}>入库策略</Link>
        </Button>
      }
    >
      {loadError ? (
        <div className="px-5">
          <WorkspaceNotice
            retry={() => {
              if (datasetQuery.isError) void datasetQuery.refetch()
              if (tablesQuery.isFetchNextPageError) void fetchNextPage({ cancelRefetch: false })
              else if (tablesQuery.isError) void tablesQuery.refetch()
            }}
            pending={isLoading}
          >
            {formatApiError(loadError, '表格读取失败')}
          </WorkspaceNotice>
        </div>
      ) : null}
      {showEmptyStage ? (
        <TableAssetsEmptyState datasetId={datasetId} />
      ) : (
        <DirectoryWorkspace
          pane={pane}
          onPaneChange={setPane}
          directoryLabel="表格目录"
          detailLabel="当前表格"
          directory={
            <>
              <div className={ws.directoryHeader}>
                <h2 className={ws.sectionTitle}>表格目录</h2>
                <p className={ws.muted}>
                  {tablesQuery.isPending
                    ? '正在读取…'
                    : tablesQuery.isError
                      ? '目录读取失败'
                      : `已加载 ${items.length} 张表`}
                </p>
              </div>
              {items.map((item) => {
                const tableLabel = getTableLabel(item)
                return (
                  <button
                    key={item.table_id}
                    type="button"
                    className={ws.directoryRow}
                    data-selected={selectedTable?.table_id === item.table_id}
                    aria-label={`选择表 ${tableLabel}`}
                    onClick={() => {
                      setSelectedTableId(item.table_id)
                      setPane('detail')
                    }}
                  >
                    <strong title={tableLabel}>{tableLabel}</strong>
                    <small>
                      {item.row_count} 行 · {item.col_count} 列
                    </small>
                    {item.document_filename ? <small>{item.document_filename}</small> : null}
                  </button>
                )
              })}
              {hasMoreTableDocuments && (
                <Button
                  variant="ghost"
                  className="mx-3 my-2"
                  disabled={tablesQuery.isFetching}
                  onClick={() => {
                    void fetchNextPage({ cancelRefetch: false })
                  }}
                >
                  {tablesQuery.isFetchingNextPage ? '正在读取更多文档…' : '读取更多表格'}
                </Button>
              )}
            </>
          }
        >
          {selectedTable === undefined ? (
            <div className={ws.empty}>
              <h2>
                {tablesQuery.isPending || scanningTableDocuments
                  ? '正在读取表格目录…'
                  : tablesQuery.isError
                    ? '表格目录读取失败'
                    : selectedTableId !== null
                      ? '当前表格不在已加载的目录中'
                      : '尚未读取到可展示表格'}
              </h2>
              <p>
                {items.length
                  ? '从目录选择一张表，查看数据或发起查询。'
                  : '含表格的文档解析入库后，可在这里查看和查询。'}
              </p>
            </div>
          ) : (
            <Tabs defaultValue="data">
              <TableDetails
                key={selectedTable.table_id}
                datasetId={datasetId}
                directoryTable={selectedTable}
                question={question}
                onQuestionChange={setQuestion}
                semFilterInstruction={semFilterInstruction}
                onSemFilterInstructionChange={setSemFilterInstruction}
              />
            </Tabs>
          )}
        </DirectoryWorkspace>
      )}
    </OperationalWorkspace>
  )
}

function TableDetails({
  datasetId,
  directoryTable,
  question,
  onQuestionChange,
  semFilterInstruction,
  onSemFilterInstructionChange,
}: Readonly<{
  datasetId: string
  directoryTable: DatasetTableAsset
  question: string
  onQuestionChange: (text: string) => void
  semFilterInstruction: string
  onSemFilterInstructionChange: (instruction: string) => void
}>) {
  const tableId = directoryTable.table_id
  const [querySql, setQuerySql] = useState(`SELECT * FROM "sheet_${directoryTable.sheet_index}" LIMIT 20`)
  const detailQuery = useQuery({
    queryKey: queryKeys.datasets.tableAsset(datasetId, tableId),
    queryFn: ({ signal }) =>
      datasetApi.getTable(datasetId, tableId, { include_columns: true, include_sample_rows: true }, { signal }),
  })
  const sqlRun = useMutation({
    networkMode: 'always',
    mutationFn: (sql: string) => datasetApi.queryTable(datasetId, tableId, { sql }),
    onError: (error) => reportClientError('Dataset table SQL query failed', error),
  })
  const questionRun = useMutation({
    networkMode: 'always',
    mutationFn: (text: string) => datasetApi.askTable(datasetId, tableId, { question: text }),
    onError: (error) => reportClientError('Dataset table question answering failed', error),
  })
  const filterRun = useMutation({
    networkMode: 'always',
    mutationFn: (instruction: string) =>
      datasetApi.lotusSemFilter(datasetId, tableId, { user_instruction: instruction, strategy: 'cot' }),
    onError: (error) => reportClientError('Dataset table semantic filter failed', error),
  })
  const detail = detailQuery.data
  const table = detail ?? directoryTable
  const trimmedQuestion = question.trim()
  const trimmedInstruction = semFilterInstruction.trim()

  return (
    <>
      <div className={ws.sectionHeading}>
        <div>
          <h2 className={ws.sectionTitle}>{getTableLabel(table)}</h2>
          <p className={ws.muted}>
            {table.document_filename && `${table.document_filename} · `}
            {table.row_count} 行 · {table.col_count} 列
          </p>
        </div>
      </div>
      {detailQuery.isError ? (
        <WorkspaceNotice
          retry={() => {
            void detailQuery.refetch()
          }}
          pending={detailQuery.isFetching}
        >
          {formatApiError(detailQuery.error, '表格详情读取失败')}
        </WorkspaceNotice>
      ) : null}
      <TabsList className={ws.tabList} aria-label="表格工具">
        <TabsTrigger value="data">数据预览</TabsTrigger>
        <TabsTrigger value="sql">SQL 查询</TabsTrigger>
        <TabsTrigger value="ask">表格问答</TabsTrigger>
        <TabsTrigger value="filter">语义筛选</TabsTrigger>
      </TabsList>
      <TabsContent value="data" className={ws.tabContent}>
        {detailQuery.isPending && <p className="py-4 text-sm text-muted-foreground">正在读取表格详情…</p>}
        {detail !== undefined && (
          <>
            <section className={ws.section}>
              <h3 className={ws.sectionTitle}>字段</h3>
              <div className={ws.tableScroll}>
                <table className={ws.table} aria-label="表格字段">
                  <thead>
                    <tr>
                      <th>名称</th>
                      <th>类型</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.columns.map((column) => (
                      <tr key={column.name}>
                        <td>{column.name}</td>
                        <td>{column.dtype ?? '未返回'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            <section className={ws.section}>
              <h3 className={ws.sectionTitle}>样例数据</h3>
              <div className={ws.tableScroll}>
                <table className={ws.table} aria-label="表格样例数据">
                  <thead>
                    <tr>
                      {detail.columns.map((column) => (
                        <th key={column.name}>{column.name}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {detail.sample_rows.map((row, index) => (
                      <tr key={index}>
                        {detail.columns.map((column) => (
                          <td key={column.name}>{formatTableCell(row[column.name])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {detail.sample_rows.length === 0 && (
                  <p className="py-4 text-sm text-muted-foreground">未返回样例数据。</p>
                )}
              </div>
            </section>
          </>
        )}
      </TabsContent>
      <TabsContent value="sql" className={ws.tabContent}>
        <section className={ws.section}>
          <Label htmlFor="table-sql">SQL 查询语句</Label>
          <Textarea
            id="table-sql"
            value={querySql}
            onChange={(event) => setQuerySql(event.target.value)}
            className="my-3 min-h-32 font-mono text-sm"
          />
          <Button disabled={sqlRun.isPending || !querySql.trim()} onClick={() => sqlRun.mutate(querySql)}>
            <Play />
            {sqlRun.isPending ? '正在查询…' : '执行查询'}
          </Button>
          {sqlRun.isError && (
            <WorkspaceNotice>{formatApiError(sqlRun.error, '查询失败，只支持只读 SQL。')}</WorkspaceNotice>
          )}
          {sqlRun.data && <TableResult result={sqlRun.data} />}
        </section>
      </TabsContent>
      <TabsContent value="ask" className={ws.tabContent}>
        <section className={ws.section}>
          <Label htmlFor="table-question">向当前表格提问</Label>
          <Input
            id="table-question"
            className="my-3"
            value={question}
            onChange={(event) => onQuestionChange(event.target.value)}
            placeholder="例如：按地区汇总销售额"
          />
          <Button
            disabled={questionRun.isPending || trimmedQuestion === ''}
            onClick={() => questionRun.mutate(trimmedQuestion)}
          >
            <Sparkles />
            {questionRun.isPending ? '正在查询…' : '查询表格'}
          </Button>
          {questionRun.isError && <WorkspaceNotice>{formatApiError(questionRun.error, '问答失败')}</WorkspaceNotice>}
          {questionRun.data ? (
            <div className="mt-5 space-y-4 text-sm leading-7">
              <p>{questionRun.data.answer}</p>
              {questionRun.data.sql ? (
                <pre className="overflow-auto bg-muted/30 p-3 text-xs">{questionRun.data.sql}</pre>
              ) : null}
              {questionRun.data.data ? <TableResult result={questionRun.data.data} /> : null}
            </div>
          ) : null}
        </section>
      </TabsContent>
      <TabsContent value="filter" className={ws.tabContent}>
        <section className={ws.section}>
          <Label htmlFor="table-sem-filter">筛选条件</Label>
          <Input
            id="table-sem-filter"
            className="my-3"
            value={semFilterInstruction}
            onChange={(event) => onSemFilterInstructionChange(event.target.value)}
            placeholder="描述要保留的行"
          />
          <Button
            disabled={filterRun.isPending || trimmedInstruction === ''}
            onClick={() => filterRun.mutate(trimmedInstruction)}
          >
            <Play />
            {filterRun.isPending ? '正在筛选…' : '筛选数据'}
          </Button>
          {filterRun.isError && <WorkspaceNotice>{formatApiError(filterRun.error, '语义过滤失败')}</WorkspaceNotice>}
          {filterRun.data && <TableResult result={filterRun.data} />}
        </section>
      </TabsContent>
    </>
  )
}
