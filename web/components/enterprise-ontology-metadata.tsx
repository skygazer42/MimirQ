'use client'

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { enterpriseOntologyApi } from '@/lib/api/enterprise-ontology'
import type {
  EnterpriseOntologyMetadataStatus as FieldReview,
  EnterpriseOntologySourceSpan as SourceSpan,
} from '@/types/enterprise-ontology'
import styles from './enterprise-ontology-published.module.css'

type Run = (action: string, task: () => Promise<void>) => Promise<void>

const states = { missing: '缺少原文证据', pending: '待确认', conflict: '证据冲突', confirmed: '已确认' } as const

export function OntologyMetadataReview({
  ontologyId,
  versionId,
  documentId,
  pipelineHash,
  fields,
  run,
}: {
  ontologyId: string
  versionId: string
  documentId: string
  pipelineHash?: string
  fields: Record<string, { label?: string | null; method?: 'extract' | 'manual'; multiple?: boolean }>
  run: Run
}) {
  const [expanded, setExpanded] = useState(false)
  const client = useQueryClient()
  const versionPath = '/kg/ontologies/' + ontologyId + '/versions/' + versionId
  const key = ['enterprise-ontology', 'metadata', versionPath, documentId, pipelineHash]
  const params = pipelineHash ? { pipeline_hash: pipelineHash } : undefined
  const metadata = useQuery({
    queryKey: key,
    queryFn: async ({ signal }) =>
      await enterpriseOntologyApi.getDocumentMetadata(ontologyId, versionId, documentId, params, { signal }),
    enabled: expanded,
    retry: false,
  })

  return (
    <details className={styles.metadataReview} onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary className="cursor-pointer font-medium">复核文档元数据</summary>
      <section className="mt-3 grid gap-3" aria-label="文档元数据">
        {metadata.isFetching && <p className="text-muted-foreground">正在读取文档元数据</p>}
        {metadata.isError && (
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-destructive" role="alert">
              {metadata.error.message}
            </p>
            <Button type="button" variant="outline" size="sm" onClick={() => void metadata.refetch()}>
              重试读取元数据
            </Button>
          </div>
        )}
        {Object.entries(metadata.data ?? {}).map(([id, item]) => (
          <MetadataField
            key={id}
            label={fields[id]?.label || id}
            item={item}
            multiple={fields[id]?.multiple ?? false}
            manual={fields[id]?.method === 'manual'}
            ontologyId={ontologyId}
            versionId={versionId}
            documentId={documentId}
            pipelineHash={pipelineHash}
            onConfirm={(candidateIds, span) =>
              run('确认文档元数据', async () => {
                await client.cancelQueries({ queryKey: key })
                const data = await enterpriseOntologyApi.reviewDocumentMetadata(
                  ontologyId,
                  versionId,
                  documentId,
                  { field: id, candidate_ids: candidateIds, ...(span ? { manual_values: [span] } : {}) },
                  params,
                )
                client.setQueryData(key, data)
              })
            }
          />
        ))}
      </section>
    </details>
  )
}

function MetadataField({
  item,
  label,
  multiple,
  manual,
  ontologyId,
  versionId,
  documentId,
  pipelineHash,
  onConfirm,
}: {
  item: FieldReview
  label: string
  multiple: boolean
  manual: boolean
  ontologyId: string
  versionId: string
  documentId: string
  pipelineHash?: string
  onConfirm: (candidateIds: string[], span?: SourceSpan) => Promise<void>
}) {
  const [selected, setSelected] = useState<string[] | null>(null)
  const confirmed = item.confirmed.map((candidate) => candidate.id)
  const checkedIds = selected ?? confirmed
  const hasChanges = checkedIds.length !== confirmed.length || checkedIds.some((id) => !confirmed.includes(id))

  return (
    <fieldset className={styles.metadataField}>
      <legend className="font-medium">{label}</legend>
      <p className={styles.statusBadge} data-state={item.state}>
        {states[item.state]}
      </p>
      {item.candidates.map((candidate) => (
        <label className={styles.metadataCandidate} key={candidate.id}>
          <input
            type="checkbox"
            className="mt-1"
            checked={checkedIds.includes(candidate.id)}
            onChange={(event) => {
              setSelected(
                event.target.checked
                  ? multiple
                    ? [...checkedIds, candidate.id]
                    : [candidate.id]
                  : checkedIds.filter((id) => id !== candidate.id),
              )
            }}
          />
          <span className="grid min-w-0 gap-1">
            <span className="font-medium break-all">{String(candidate.value)}</span>
            <span className="text-muted-foreground">
              {candidate.page !== null && '第 ' + candidate.page + ' 页 · '}
              字符 {candidate.evidence.start_char}–{candidate.evidence.end_char}
            </span>
            <span className="whitespace-pre-wrap break-words border-s-2 pl-2">{candidate.evidence.quote}</span>
          </span>
        </label>
      ))}
      {item.candidates.length > 0 && (
        <Button
          className="justify-self-start"
          type="button"
          size="sm"
          variant="outline"
          disabled={!hasChanges}
          onClick={() => void onConfirm(checkedIds)}
        >
          {checkedIds.length ? '确认选中证据' : '撤销当前确认'}
        </Button>
      )}
      {manual && (
        <ManualSpan
          ontologyId={ontologyId}
          versionId={versionId}
          documentId={documentId}
          pipelineHash={pipelineHash}
          onSubmit={(span) => onConfirm(multiple ? checkedIds : [], span)}
        />
      )}
    </fieldset>
  )
}

function ManualSpan({
  ontologyId,
  versionId,
  documentId,
  pipelineHash,
  onSubmit,
}: {
  ontologyId: string
  versionId: string
  documentId: string
  pipelineHash?: string
  onSubmit: (span: SourceSpan) => Promise<void>
}) {
  const [expanded, setExpanded] = useState(false)
  const [chunk, setChunk] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const path = '/kg/ontologies/' + ontologyId + '/versions/' + versionId + '/documents/' + documentId + '/evidence'
  const chunks = useQuery({
    queryKey: ['enterprise-ontology', 'evidence-chunks', path, pipelineHash],
    queryFn: async ({ signal }) =>
      await enterpriseOntologyApi.listDocumentEvidence(
        ontologyId,
        versionId,
        documentId,
        { pipeline_hash: pipelineHash },
        { signal },
      ),
    enabled: expanded,
    retry: false,
  })

  return (
    <details onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary className="cursor-pointer">从原文补录</summary>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <label className="grid gap-1 sm:col-span-2">
          原文分块
          <select
            className="h-9 rounded-md border border-input bg-background px-2"
            value={chunk}
            onChange={(event) => setChunk(event.target.value)}
          >
            <option value="">选择分块</option>
            {chunks.data?.map((item, index) => (
              <option key={item.chunk_id} value={item.chunk_id}>
                {item.page !== null ? `第 ${item.page} 页 · ` : ''}分块 {index + 1}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1">
          起点字符（从 0 开始）
          <Input type="number" min={0} value={start} onChange={(event) => setStart(event.target.value)} />
        </label>
        <label className="grid gap-1">
          终点字符（不含）
          <Input type="number" min={1} value={end} onChange={(event) => setEnd(event.target.value)} />
        </label>
        {chunks.isError && (
          <p role="alert" className="text-destructive sm:col-span-2">
            原文分块不可用
          </p>
        )}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="justify-self-start"
          disabled={!chunk || !start || !end || Number(start) < 0 || Number(end) <= Number(start)}
          onClick={() => void onSubmit({ chunk_id: chunk, start_char: Number(start), end_char: Number(end) })}
        >
          确认原文区间
        </Button>
      </div>
    </details>
  )
}
