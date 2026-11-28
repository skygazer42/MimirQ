'use client'

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { documentApi } from '@/lib/api/documents'
import { enterpriseOntologyApi } from '@/lib/api/enterprise-ontology'
import { extractHttpStatus, formatApiError } from '@/lib/api-errors'
import type { OntologyGraphItem, OntologyGraphTarget } from '../graph-page-utils'
import { OntologyChunkEditor } from './ontology-chunk-editor'

const field = 'grid min-w-0 gap-1.5 text-sm'
const select = 'h-11 w-full min-w-0 rounded-md border border-input bg-background px-2 sm:h-9'

export function OntologyGraphTool({
  datasetId,
  documentIds,
  versionId,
  target,
  onCloseTarget,
  onSaved,
}: {
  datasetId: string
  documentIds: string[]
  versionId: string
  target: OntologyGraphTarget | null
  onCloseTarget: () => void
  onSaved: () => void
}) {
  const [browseOpen, setBrowseOpen] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [closeWarning, setCloseWarning] = useState(false)
  const open = browseOpen || target !== null

  function close() {
    setBrowseOpen(false)
    onCloseTarget()
    setDirty(false)
    setCloseWarning(false)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && dirty) {
          setCloseWarning(true)
          return
        }
        if (next) setBrowseOpen(true)
        else close()
      }}
    >
      <DialogTrigger asChild>
        <Button type="button" variant="outline">
          本体图谱
        </Button>
      </DialogTrigger>
      <DialogContent
        className="flex max-h-[94dvh] w-[calc(100%-1rem)] max-w-5xl flex-col overflow-hidden p-0"
        onOpenAutoFocus={
          target
            ? (event) => {
                event.preventDefault()
                if (event.target instanceof HTMLElement) event.target.focus()
              }
            : undefined
        }
      >
        <DialogHeader className="px-4 pt-4 pr-12 text-left sm:px-6 sm:pt-5">
          <DialogTitle>本体图谱</DialogTitle>
          <DialogDescription>核对文档原文，修正当前本体版本中的实体和关系。</DialogDescription>
        </DialogHeader>
        {closeWarning && dirty && (
          <div className="mx-4 flex shrink-0 flex-wrap items-center gap-2 text-sm sm:mx-6">
            <span role="status">有未保存的修正。</span>
            <Button type="button" size="sm" variant="outline" onClick={() => setCloseWarning(false)}>
              继续编辑
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={close}>
              放弃修改并关闭
            </Button>
          </div>
        )}
        {open && (
          <OntologyGraphDocuments
            datasetId={datasetId}
            documentIds={documentIds}
            versionId={versionId}
            target={target}
            dirty={dirty}
            onSaved={onSaved}
            onDirtyChange={(changed) => {
              setDirty(changed)
              if (!changed) setCloseWarning(false)
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

function OntologyGraphDocuments({
  datasetId,
  documentIds,
  versionId,
  target,
  dirty,
  onDirtyChange,
  onSaved,
}: {
  datasetId: string
  documentIds: string[]
  versionId: string
  target: OntologyGraphTarget | null
  dirty: boolean
  onDirtyChange: (dirty: boolean) => void
  onSaved: () => void
}) {
  const [filter, setFilter] = useState('')
  const [documentId, setDocumentId] = useState(target?.documentId ?? (documentIds.length === 1 ? documentIds[0] : ''))
  const [chunkId, setChunkId] = useState(target?.chunkId)
  const [initialItem, setInitialItem] = useState<OntologyGraphItem | undefined>(target?.item)
  const [message, setMessage] = useState('')
  const client = useQueryClient()
  const graphKey = ['enterprise-ontology', 'document-graph', datasetId, versionId, documentId, chunkId ?? 'first']
  const documents = useQuery({
    queryKey: ['enterprise-ontology', 'graph-documents', datasetId, documentIds, filter.trim()],
    queryFn: async ({ signal }) => {
      if (documentIds.length) {
        const items = await Promise.all(documentIds.map((id) => documentApi.get(id, undefined, { signal })))
        return { items, total: items.length }
      }
      return documentApi.list(
        { dataset_id: datasetId, q: filter.trim() || undefined, limit: 50, lifecycle: 'active' },
        { signal },
      )
    },
    retry: false,
  })
  const graph = useQuery({
    queryKey: graphKey,
    queryFn: ({ signal }) => enterpriseOntologyApi.getDocumentGraph(datasetId, documentId, chunkId, { signal }),
    enabled: Boolean(documentId),
    staleTime: Infinity,
    refetchOnMount: 'always',
    retry: false,
  })
  const versionChanged = graph.data !== undefined && graph.data.version_id !== versionId
  const graphInaccessible = graph.isError && [401, 403, 404].includes(extractHttpStatus(graph.error) ?? 0)
  const view = versionChanged || graphInaccessible ? undefined : graph.data
  const options = documents.data?.items ?? []
  const documentInResults = options.some((item) => item.id === documentId)
  const documentName = documents.data?.items.find((item) => item.id === documentId)?.filename
  return (
    <div className="grid min-h-0 gap-4 overflow-y-auto px-4 pb-5 sm:px-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {documentIds.length === 0 && (
          <label className={`${field} col-span-2 sm:col-span-1`}>
            查找文档
            <Input value={filter} onChange={(event) => setFilter(event.target.value)} disabled={dirty} />
          </label>
        )}
        <label className={field}>
          文档
          <select
            className={select}
            value={documentId}
            disabled={dirty || documents.isPending}
            onChange={(event) => {
              setDocumentId(event.target.value)
              setChunkId(undefined)
              setInitialItem(undefined)
              setMessage('')
            }}
          >
            <option value="">{documents.isPending ? '正在读取文档…' : '选择文档'}</option>
            {documentId && !documentInResults && <option value={documentId}>当前文档</option>}
            {options.map((item) => (
              <option key={item.id} value={item.id}>
                {item.filename}
              </option>
            ))}
          </select>
        </label>
        {view && (
          <label className={field}>
            原文分块
            <select
              className={select}
              value={view.chunk.chunk_id}
              disabled={dirty || graph.isFetching}
              onChange={(event) => {
                setChunkId(event.target.value)
                setInitialItem(undefined)
                setMessage('')
              }}
            >
              {view.chunks.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.page === null ? '' : `第 ${item.page} 页 · `}分块 {item.index + 1}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {documents.isError && (
        <p role="alert" className="text-sm text-destructive">
          {formatApiError(documents.error, '读取文档失败')}
        </p>
      )}
      {options.length === 0 && documents.isSuccess && <p className="text-sm text-muted-foreground">没有匹配的文档。</p>}
      {graph.isFetching && !dirty && (
        <p role="status" className="text-sm text-muted-foreground">
          正在读取本体证据…
        </p>
      )}
      {graph.isError && (
        <p role="alert" className="text-sm text-destructive">
          {extractHttpStatus(graph.error) === 404
            ? '这份文档暂无可编辑的本体证据。请检查版本应用里的文档准备状态。'
            : formatApiError(graph.error, '读取本体图谱失败')}
        </p>
      )}
      {versionChanged && (
        <p role="alert" className="text-sm text-destructive">
          本体版本已切换，请重新加载图谱。
        </p>
      )}
      {message && (
        <p role="status" className="text-sm text-muted-foreground">
          {message}
        </p>
      )}
      {view && (!graph.isFetching || dirty) && (
        <OntologyChunkEditor
          key={view.chunk.chunk_id + ':' + view.revision}
          datasetId={datasetId}
          documentName={documentName}
          view={view}
          initialItem={initialItem}
          onDirtyChange={onDirtyChange}
          onReload={() => graph.refetch({ throwOnError: true })}
          onSaved={(restored, updated) => {
            setInitialItem(undefined)
            client.setQueryData(graphKey, updated)
            setMessage(restored ? '已恢复模型抽取结果' : '图谱修正已保存')
            onSaved()
          }}
        />
      )}
    </div>
  )
}
