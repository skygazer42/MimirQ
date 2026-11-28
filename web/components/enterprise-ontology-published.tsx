'use client'

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { Database, FileText, Zap } from '@/components/icons'
import { Link } from '@/i18n/navigation'
import { enterpriseOntologyApi } from '@/lib/api/enterprise-ontology'
import type {
  EnterpriseOntologyDefinitionView as PublishedDefinition,
  EnterpriseOntologyVersionView as OntologyVersion,
  EnterpriseOntologyEdoProvenance as EdoProvenance,
  EnterpriseOntologyPreparedDocument as PreparedDocument,
  EnterpriseOntologyDatasetBinding as DatasetBinding,
  EnterpriseOntologyQuestion as Question,
  EnterpriseOntologyMetricView as Metric,
  EnterpriseOntologyObject as ObjectFact,
  EnterpriseOntologyAnswerView as Answer,
  EnterpriseOntologyKnowledgeAnswer as KnowledgeAnswer,
  EnterpriseOntologyDocumentDraft as Draft,
  EnterpriseOntologyActionDefinitionView as ActionDefinition,
  EnterpriseOntologyHeaders,
} from '@/types/enterprise-ontology'
import { datasetApi } from '@/lib/api/datasets'
import { documentApi } from '@/lib/api/documents'
import { buildChunkPreviewDocumentHref } from '@/lib/chunk-preview-links'
import { downloadBlob } from '@/lib/download'
import { OntologyActionForm } from './enterprise-ontology-action-form'
import { OntologyMetadataReview } from './enterprise-ontology-metadata'
import { PublishedOntologyWorkflows } from './enterprise-ontology-workflows'
import styles from './enterprise-ontology-published.module.css'

type Run = (action: string, task: () => Promise<void>) => Promise<void>

const base = '/kg/ontologies'
const field = 'grid min-w-0 gap-1 text-sm'
const select =
  'h-9 min-w-0 w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50'
const textLink = 'break-all text-foreground underline underline-offset-4'
const scopeFields = 'grid min-w-0 gap-3 md:grid-cols-2'
const status = 'text-sm text-muted-foreground'
const ruleOutcomes = { true: '成立', false: '不成立', unknown: '待确认' } as const
const metricReasons: Partial<Record<string, string>> = {
  group_limit_reached: '分组数量已达到本次返回上限。',
  historical_state_unavailable: '所选时间的历史数据不可用。',
  source_window_incomplete: '来源数据未覆盖完整的统计窗口。',
  source_truncated: '来源数据超出本次扫描上限。',
  formula_operand_unavailable: '公式所需的指标缺少完整数据。',
  zero_formula_denominator: '除数为零，无法计算比例。',
}

export function OntologyEdoSource({ source }: { source: EdoProvenance }) {
  return (
    <p className="break-all text-muted-foreground">
      EDO 工作修订 {source.working_revision} · {source.status}
      {source.synced_at && ' · 同步于 ' + source.synced_at}
      {source.reason_code && ' · ' + source.reason_code}
    </p>
  )
}

function DatasetActiveStatus({ active, versions }: { active: DatasetBinding; versions: OntologyVersion[] }) {
  if (active.version_id === null) return <p className={status}>尚未绑定本体版本</p>
  const current = versions.find((item) => item.id === active.version_id)
  return (
    <p className={styles.statusBadge} data-state="succeeded">
      当前生效 · {current ? '版本 ' + current.number : active.version_id}
    </p>
  )
}

export function PublishedOntologyWorkspace({
  version,
  versions,
  ontologyId,
  edoHeaders,
  busy,
  run,
}: {
  version: OntologyVersion
  versions: OntologyVersion[]
  ontologyId: string
  edoHeaders?: EnterpriseOntologyHeaders
  busy: boolean
  run: Run
}) {
  const [datasetId, setDatasetId] = useState('')
  const [documentFilter, setDocumentFilter] = useState('')
  const [selectedDocument, setSelectedDocument] = useState<{ id: string; filename: string } | null>(null)
  const [prepared, setPrepared] = useState<PreparedDocument | null>(null)
  const [application, setApplication] = useState('metrics')
  const [question, setQuestion] = useState('')
  const [datasetIds, setDatasetIds] = useState<string[]>([])
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [knowledgeAnswer, setKnowledgeAnswer] = useState<KnowledgeAnswer | null>(null)
  const [templateId, setTemplateId] = useState('')
  const [manualFields, setManualFields] = useState<Record<string, string>>({})
  const [draft, setDraft] = useState<Draft | null>(null)
  const [savedDraftId, setSavedDraftId] = useState('')
  const [generatedDraft, setGeneratedDraft] = useState<{ id: string; templateId: string } | null>(null)
  const queryClient = useQueryClient()

  const datasets = useQuery({
    queryKey: ['enterprise-ontology', 'datasets'],
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
    retry: false,
  })
  const datasetOptions = datasets.data ?? []
  const activeKey = ['enterprise-ontology', 'dataset-active', datasetId]
  const active = useQuery({
    queryKey: activeKey,
    queryFn: async ({ signal }) => await enterpriseOntologyApi.getActiveDataset(datasetId, { signal }),
    enabled: Boolean(datasetId),
    retry: false,
  })
  const documents = useQuery({
    queryKey: ['enterprise-ontology', 'documents', datasetId, documentFilter.trim()],
    queryFn: ({ signal }) =>
      documentApi.list(
        { dataset_id: datasetId, q: documentFilter.trim() || undefined, limit: 50, lifecycle: 'active' },
        { signal },
      ),
    enabled: Boolean(datasetId),
    retry: false,
  })
  const path = base + '/' + ontologyId + '/versions/' + version.id
  const definition = version.definition
  const templates = definition.document_templates ?? {}
  const metadataFields = definition.document_metadata ?? {}
  const template = templates[templateId]
  const draftTemplate =
    generatedDraft && generatedDraft.id === draft?.id ? templates[generatedDraft.templateId] : undefined
  const questionMode = application === 'metrics' ? 'metrics' : 'knowledge'
  const questionPayload: Question = {
    question: question.trim(),
    dataset_ids: questionMode === 'knowledge' ? datasetIds : [],
  }
  const actions = definition.actions ?? {}
  const hasActions = Object.keys(actions).length > 0
  const hasWorkflows = Object.keys(definition.action_workflows ?? {}).length > 0

  function clearResults() {
    setAnswer(null)
    setKnowledgeAnswer(null)
    setDraft(null)
  }

  function prepareDocument() {
    if (!selectedDocument) return
    setPrepared(null)
    void run('准备文档证据', async () => {
      const data = await enterpriseOntologyApi.prepareDocument(ontologyId, version.id, {
        document_id: selectedDocument.id,
      })
      setPrepared(data)
      await queryClient.invalidateQueries({ queryKey: ['enterprise-ontology', 'metadata', path, data.document_id] })
    })
  }

  function activate() {
    void run('激活所选版本', async () => {
      await queryClient.cancelQueries({ queryKey: activeKey })
      await enterpriseOntologyApi.activateDataset(ontologyId, version.id, datasetId, { headers: edoHeaders })
      const result = await active.refetch({ throwOnError: true })
      if (result.data?.version_id !== version.id) throw new Error('知识库已切换到其他版本，请检查当前生效版本')
    })
  }

  function ask() {
    void run('查询已发布版本', async () => {
      if (questionMode === 'knowledge') {
        const data = await enterpriseOntologyApi.askKnowledgeVersion(
          ontologyId,
          version.id,
          { question: questionPayload.question, dataset_ids: datasetIds },
          { headers: edoHeaders },
        )
        setKnowledgeAnswer(data)
      } else {
        const data = await enterpriseOntologyApi.askVersion(ontologyId, version.id, questionPayload, {
          headers: edoHeaders,
        })
        setAnswer(data)
      }
    })
  }

  function createDraft() {
    setDraft(null)
    void run('生成文书草稿', async () => {
      const manual_fields = Object.fromEntries(Object.entries(manualFields).filter(([, value]) => value.trim()))
      const data = await enterpriseOntologyApi.createDocumentDraft(
        ontologyId,
        version.id,
        { template_id: templateId, question: questionPayload, manual_fields },
        { headers: edoHeaders },
      )
      setDraft(data)
      setSavedDraftId(data.id)
      setGeneratedDraft({ id: data.id, templateId })
    })
  }

  function reopenDraft(id: string) {
    setDraft(null)
    void run('读取文书草稿', async () => {
      const data = await enterpriseOntologyApi.getDocumentDraft(ontologyId, version.id, id.trim(), {
        headers: edoHeaders,
      })
      setDraft(data)
    })
  }

  function exportDraft(final: boolean) {
    if (!draft) return
    void run('下载 DOCX 草稿', async () => {
      const data = await enterpriseOntologyApi.exportDocumentDraft(ontologyId, version.id, draft.id, final, {
        headers: edoHeaders,
      })
      downloadBlob(draft.title + '.docx', data)
    })
  }

  return (
    <fieldset className={styles.workspace} disabled={busy}>
      <Tabs value={application} onValueChange={setApplication} className={styles.application}>
        <TabsList aria-label="本体应用" className={styles.applicationTabs}>
          <TabsTrigger value="metrics">问数</TabsTrigger>
          <TabsTrigger value="knowledge">本体＋知识库问答</TabsTrigger>
          <TabsTrigger value="actions">执行</TabsTrigger>
        </TabsList>
        <TabsContent value={questionMode} forceMount className="min-w-0 data-[state=inactive]:hidden">
          <section
            className={styles.queryWorkspace}
            aria-label={questionMode === 'metrics' ? '问数' : '本体＋知识库问答'}
          >
            <div className={styles.queryControls}>
              <label className={field}>
                业务问题
                <Textarea
                  maxLength={4000}
                  rows={3}
                  value={question}
                  onChange={(event) => {
                    setQuestion(event.target.value)
                    clearResults()
                  }}
                />
              </label>
              {questionMode === 'knowledge' && (
                <>
                  <label className={field}>
                    添加问答知识库
                    <select
                      className={select}
                      value=""
                      disabled={datasetIds.length >= 20}
                      onChange={(event) => {
                        setDatasetIds([...datasetIds, event.target.value])
                        clearResults()
                      }}
                    >
                      <option value="">{datasetIds.length >= 20 ? '最多选择 20 个知识库' : '选择原文来源'}</option>
                      {datasetOptions
                        .filter((item) => !datasetIds.includes(item.id))
                        .map((dataset) => (
                          <option value={dataset.id} key={dataset.id}>
                            {dataset.name}
                          </option>
                        ))}
                    </select>
                  </label>
                  {datasetIds.length > 0 && (
                    <ul className="flex flex-wrap gap-2">
                      {datasetIds.map((id) => {
                        const name = datasetOptions.find((item) => item.id === id)?.name ?? id
                        return (
                          <li key={id} className="flex min-w-0 items-center gap-1 rounded-md bg-muted pl-2 text-sm">
                            <span className="break-words">{name}</span>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              aria-label={'移除问答知识库 ' + name}
                              onClick={() => {
                                setDatasetIds(datasetIds.filter((item) => item !== id))
                                clearResults()
                              }}
                            >
                              移除
                            </Button>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </>
              )}
              <Button
                type="button"
                className="justify-self-start"
                disabled={!questionPayload.question || (questionMode === 'knowledge' && !datasetIds.length)}
                onClick={ask}
              >
                {questionMode === 'metrics' ? '查询数据' : '开始问答'}
              </Button>
            </div>
            <div className={styles.queryResults}>
              {questionMode === 'metrics' && answer && <QuestionEvidence answer={answer} definition={definition} />}
              {questionMode === 'knowledge' && knowledgeAnswer && (
                <section className="grid min-w-0 grid-cols-1 gap-3 text-sm" aria-label="融合回答">
                  <div className="min-w-0 break-words [&_table]:w-full [&_th]:text-left [&_td]:align-top">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      disallowedElements={['img']}
                      components={{
                        table: ({ children }) => (
                          <div className="min-w-0 overflow-x-auto">
                            <table>{children}</table>
                          </div>
                        ),
                      }}
                    >
                      {knowledgeAnswer.answer}
                    </ReactMarkdown>
                  </div>
                  {knowledgeAnswer.citations.length > 0 && (
                    <section className="grid gap-1" aria-label="引用来源">
                      <h4 className="font-medium">引用来源</h4>
                      <ol className="list-decimal space-y-1 pl-5">
                        {knowledgeAnswer.citations.map((citation, index) => (
                          <li key={citation.chunk_id + ':' + index}>
                            <Link className={textLink} href={buildChunkPreviewDocumentHref(citation.document_id)}>
                              {citation.document_name}
                            </Link>
                            {citation.page_number != null && <> · 第 {citation.page_number} 页</>}
                          </li>
                        ))}
                      </ol>
                    </section>
                  )}
                  <details className="min-w-0">
                    <summary className="cursor-pointer">本体证据</summary>
                    <div className="mt-2">
                      <QuestionEvidence answer={knowledgeAnswer.ontology} definition={definition} />
                    </div>
                  </details>
                </section>
              )}
            </div>
          </section>
        </TabsContent>
        <TabsContent value="actions" forceMount className={styles.execution + ' data-[state=inactive]:hidden'}>
          {(knowledgeAnswer || answer) && (
            <section className={styles.recentEvidence} aria-label="最近问答证据">
              <h3 className="text-sm font-semibold">最近问答证据</h3>
              {knowledgeAnswer && <ReactMarkdown disallowedElements={['img']}>{knowledgeAnswer.answer}</ReactMarkdown>}
              <details open>
                <summary className="cursor-pointer">本体与原文证据</summary>
                <QuestionEvidence answer={knowledgeAnswer?.ontology ?? answer!} definition={definition} />
              </details>
            </section>
          )}
          {!hasActions && !hasWorkflows && <p className={status}>该版本没有已发布的业务动作</p>}
          {hasActions && (
            <PublishedActions
              definition={definition}
              actions={actions}
              ontologyId={ontologyId}
              versionId={version.id}
              run={run}
              edoHeaders={edoHeaders}
            />
          )}
          {hasWorkflows && (
            <PublishedOntologyWorkflows
              definition={definition}
              ontologyId={ontologyId}
              versionId={version.id}
              edoHeaders={edoHeaders}
              run={run}
            />
          )}
        </TabsContent>
      </Tabs>
      <section className={styles.evidence} aria-label="文档证据与知识库">
        <h3 className={styles.cardHeading}>
          <span className={styles.sectionIcon} data-tone="source" aria-hidden="true">
            <Database />
          </span>
          文档证据与知识库
        </h3>
        {datasets.isPending && <p className={status}>正在读取知识库</p>}
        {datasets.isError && (
          <div className="flex items-center gap-2 text-sm">
            <p className="text-destructive" role="alert">
              {datasets.error.message}
            </p>
            <Button type="button" variant="outline" size="sm" onClick={() => void datasets.refetch()}>
              重试读取知识库
            </Button>
          </div>
        )}
        <div className={scopeFields}>
          <label className={field}>
            准备与激活知识库
            <select
              className={select}
              value={datasetId}
              onChange={(event) => {
                setDatasetId(event.target.value)
                setDocumentFilter('')
                setSelectedDocument(null)
                setPrepared(null)
              }}
            >
              <option value="">{datasets.isSuccess && !datasetOptions.length ? '暂无可用知识库' : '选择知识库'}</option>
              {datasetOptions.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name}
                </option>
              ))}
            </select>
          </label>
          {datasetId && (
            <label className={field}>
              按文件名查找文档
              <Input value={documentFilter} onChange={(event) => setDocumentFilter(event.target.value)} />
            </label>
          )}
        </div>
        {datasetId && (
          <label className={field}>
            待准备文档
            <select
              className={select}
              value={selectedDocument?.id ?? ''}
              onChange={(event) => {
                setSelectedDocument(documents.data?.items.find((item) => item.id === event.target.value) ?? null)
                setPrepared(null)
              }}
            >
              <option value="">
                {documents.isPending
                  ? '正在读取文档'
                  : documents.data?.items.length === 0
                    ? '未找到文档'
                    : '选择已解析的文档'}
              </option>
              {selectedDocument && !documents.data?.items.some((item) => item.id === selectedDocument.id) && (
                <option value={selectedDocument.id}>{selectedDocument.filename}</option>
              )}
              {documents.data?.items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.filename}
                </option>
              ))}
            </select>
            {(documents.data?.total ?? 0) > 50 && (
              <span className={status}>显示前 50 份文档，可按文件名缩小范围。</span>
            )}
          </label>
        )}
        {documents.isError && (
          <div className="flex items-center gap-2">
            <p className="text-sm text-destructive" role="alert">
              {documents.error.message}
            </p>
            <Button type="button" variant="outline" size="sm" onClick={() => void documents.refetch()}>
              重试读取文档
            </Button>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" disabled={!selectedDocument} onClick={prepareDocument}>
            准备文档证据
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={!datasetId || active.isFetching || active.data?.version_id === version.id}
            onClick={activate}
          >
            激活所选版本
          </Button>
          {datasetId && active.isFetching && <p className={status}>正在读取生效版本</p>}
          {active.isError && (
            <p className="text-sm text-destructive" role="alert">
              {active.error.message}
            </p>
          )}
          {active.data && !active.isFetching && <DatasetActiveStatus active={active.data} versions={versions} />}
        </div>
        {prepared && (
          <p className={status}>
            已准备 {prepared.chunk_count} 个分块 ·{' '}
            <Link className={textLink} href={buildChunkPreviewDocumentHref(prepared.document_id)}>
              查看文档
            </Link>
            <span className="break-all"> · 解析版本 {prepared.pipeline_hash}</span>
          </p>
        )}
        {selectedDocument && Object.keys(metadataFields).length > 0 && (
          <OntologyMetadataReview
            key={selectedDocument.id}
            ontologyId={ontologyId}
            versionId={version.id}
            documentId={selectedDocument.id}
            pipelineHash={prepared?.pipeline_hash}
            fields={metadataFields}
            run={run}
          />
        )}
      </section>

      <section className={styles.drafts} aria-label="文书草稿">
        <h3 className={styles.cardHeading}>
          <span className={styles.sectionIcon} data-tone="document" aria-hidden="true">
            <FileText />
          </span>
          文书草稿
        </h3>
        {Object.keys(templates).length === 0 ? (
          <p className={status}>该版本没有文书模板</p>
        ) : (
          <>
            <label className={field}>
              文书模板
              <select
                className={select}
                value={templateId}
                onChange={(event) => {
                  setTemplateId(event.target.value)
                  setManualFields({})
                  setDraft(null)
                }}
              >
                <option value="">选择文书模板</option>
                {Object.entries(templates).map(([id, item]) => (
                  <option key={id} value={id}>
                    {item.title}
                  </option>
                ))}
              </select>
            </label>
            {template && (
              <>
                <div className={scopeFields}>
                  {Object.entries(template.fields)
                    .filter(([, item]) => item.source === 'manual')
                    .map(([id, item]) => (
                      <label className={field} key={id}>
                        {item.label}
                        <Input
                          aria-describedby={item.required ? 'ontology-draft-missing-note' : undefined}
                          value={manualFields[id] ?? ''}
                          onChange={(event) => {
                            setManualFields({ ...manualFields, [id]: event.target.value })
                            setDraft(null)
                          }}
                        />
                      </label>
                    ))}
                </div>
                <p id="ontology-draft-missing-note" className={status}>
                  文书沿用上方的业务问题和知识库。缺少的必填字段会标为待确认。
                </p>
                <Button
                  type="button"
                  variant="outline"
                  className="justify-self-start"
                  disabled={!questionPayload.question}
                  onClick={createDraft}
                >
                  生成文书草稿
                </Button>
              </>
            )}
          </>
        )}
        <details className="grid gap-2 text-sm">
          <summary className="cursor-pointer">打开已保存文书</summary>
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <label className={field}>
              已保存草稿 ID
              <Input value={savedDraftId} onChange={(event) => setSavedDraftId(event.target.value)} />
            </label>
            <Button
              type="button"
              variant="outline"
              disabled={!savedDraftId.trim()}
              onClick={() => reopenDraft(savedDraftId)}
            >
              打开草稿
            </Button>
          </div>
        </details>
        {draft && (
          <div className="grid gap-3">
            {draft.missing_required.length > 0 && (
              <p className={status}>
                待确认字段 · {draft.missing_required.map((id) => draftTemplate?.fields[id]?.label ?? id).join('、')}
              </p>
            )}
            <div className={styles.draftPaper}>
              <ReactMarkdown disallowedElements={['img']}>{draft.markdown}</ReactMarkdown>
            </div>
            <div className={styles.draftActions}>
              <Button type="button" variant="outline" onClick={() => exportDraft(false)}>
                下载 DOCX 草稿
              </Button>
              {draft.missing_required.length === 0 && (
                <Button type="button" variant="outline" onClick={() => exportDraft(true)}>
                  下载正式 DOCX
                </Button>
              )}
              <Button type="button" variant="ghost" onClick={() => reopenDraft(draft.id)}>
                重新读取草稿
              </Button>
              <p className="break-all font-mono text-xs text-muted-foreground">{draft.id}</p>
            </div>
          </div>
        )}
      </section>
    </fieldset>
  )
}

function Facts({ item, definition }: { item: ObjectFact; definition: PublishedDefinition }) {
  const object = definition.object_types[item.object_type]
  return (
    <dl className={styles.metadataGrid}>
      <div>
        <dt className="inline text-muted-foreground">结构化来源 · </dt>
        <dd className="inline font-mono break-all">{item.asset_id}</dd>
      </div>
      {item.edo && (
        <div>
          <dt className="sr-only">数据版本</dt>
          <dd>
            <OntologyEdoSource source={item.edo} />
          </dd>
        </div>
      )}
      {Object.entries({ ...item.key, ...item.attributes }).map(([id, value]) => {
        const property = object?.properties[id]
        return (
          <div key={id}>
            <dt className="inline text-muted-foreground">
              {typeof property === 'object' ? property.label || id : id} ·{' '}
            </dt>
            <dd className="inline break-all">{value === null ? '待确认' : String(value)}</dd>
          </div>
        )
      })}
    </dl>
  )
}

function MetricEvidence({
  result,
  definition,
  name,
}: {
  result: Metric
  definition: PublishedDefinition
  name?: string
}) {
  const metric = definition.metrics?.[result.metric]
  const { query } = result
  const groupBy = query.group_by ?? []
  const grouped = groupBy.length > 0
  const properties = metric && definition.object_types[metric.object_type]?.properties
  const reason = result.reason && (metricReasons[result.reason] ?? result.reason)
  let summary = '数据覆盖不足'
  if (grouped) {
    if (result.groups == null) summary = '分组结果不可用'
    else if (!result.complete) summary = '分组数据覆盖不足'
    else summary = result.groups.length ? `${result.groups.length} 个分组` : '无匹配的分组'
  } else if (result.complete && result.value !== null) {
    summary = [result.value, metric?.unit].filter((value) => value != null).join(' ')
  }
  return (
    <div className={styles.metricEvidence}>
      <p className={styles.metricSummary}>
        {name ?? (metric?.label || result.metric)} · {summary}
      </p>
      <dl className={styles.metadataGrid}>
        {grouped && (
          <div>
            <dt className="inline text-muted-foreground">分组维度 · </dt>
            <dd className="inline wrap-anywhere">
              {groupBy
                .map((id) => {
                  const property = properties?.[id]
                  return typeof property === 'object' ? property.label || id : id
                })
                .join('、')}
            </dd>
          </div>
        )}
        <div>
          <dt className="inline text-muted-foreground">数据资产 · </dt>
          <dd className="inline break-all font-mono">{result.asset_id}</dd>
        </div>
        {result.formula && (
          <div>
            <dt className="inline text-muted-foreground">参考指标 · </dt>
            <dd className="inline break-all">
              {definition.metrics?.[result.formula.reference_metric]?.label || result.formula.reference_metric}
              {result.formula.reference_value != null && ' · ' + result.formula.reference_value}
              {' · ' + result.formula.reference_asset_id}
            </dd>
          </div>
        )}
        {query.observed_at && (
          <div>
            <dt className="inline text-muted-foreground">观察时间 · </dt>
            <dd className="inline break-all">{query.observed_at}</dd>
          </div>
        )}
        {(query.start || query.end) && (
          <div>
            <dt className="inline text-muted-foreground">统计窗口 · </dt>
            <dd className="inline break-all">
              {query.start ?? '起始不限'} — {query.end ?? '结束不限'}
            </dd>
          </div>
        )}
        {Object.keys(query.filters).length > 0 && (
          <div>
            <dt className="inline text-muted-foreground">查询条件 · </dt>
            <dd className="inline break-all">
              {Object.entries(query.filters)
                .map(([id, value]) => id + '=' + String(value))
                .join('、')}
            </dd>
          </div>
        )}
      </dl>
      {result.source_updated_at && <p className={status}>来源更新 · {result.source_updated_at}</p>}
      {result.edo && <OntologyEdoSource source={result.edo} />}
      {!result.complete && reason && <p className={status}>{reason}</p>}
    </div>
  )
}

function QuestionEvidence({ answer, definition }: { answer: Answer; definition: PublishedDefinition }) {
  const hasGroupedRows = Boolean(answer.metric?.groups?.length || answer.function?.result.groups?.length)
  return (
    <div className={styles.evidenceCard}>
      {!answer.queries?.length &&
        (hasGroupedRows ? (
          <div className="grid min-w-0 gap-2 wrap-anywhere">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              disallowedElements={['img']}
              components={{
                table: ({ children }) => (
                  <div className="overflow-x-auto">
                    <table className="w-full tabular-nums">{children}</table>
                  </div>
                ),
                th: ({ children, style }) => (
                  <th scope="col" className="border-b px-2 py-1 text-left font-medium last:text-right" style={style}>
                    {children}
                  </th>
                ),
                td: ({ children, style }) => (
                  <td className="border-b px-2 py-1 last:text-right" style={style}>
                    {children}
                  </td>
                ),
              }}
            >
              {answer.answer}
            </ReactMarkdown>
          </div>
        ) : (
          <p className="whitespace-pre-wrap break-words">{answer.answer}</p>
        ))}
      {answer.queries?.map((query, index) => (
        <section className="grid min-w-0 gap-2" aria-label={query.label} key={query.query + ':' + index}>
          <h4 className="font-medium">{query.label}</h4>
          {query.parameters && (
            <dl className={styles.metadataGrid}>
              {Object.entries(query.parameters).map(([name, value]) => (
                <div key={name}>
                  <dt className="inline">{name} · </dt>
                  <dd className="inline">{value === null ? '—' : String(value)}</dd>
                </div>
              ))}
            </dl>
          )}
          {!query.complete && <p className={status}>该查询结果覆盖不完整</p>}
          {query.rows.length === 0 ? (
            <p className={status}>没有匹配数据</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left tabular-nums">
                <thead>
                  <tr>
                    {query.columns.map((column) => (
                      <th className="border-b px-2 py-1 font-medium" scope="col" key={column}>
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {query.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {row.map((value, columnIndex) => (
                        <td className="border-b px-2 py-1" key={columnIndex}>
                          {value === null ? '—' : String(value)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ))}
      {answer.metric && <MetricEvidence result={answer.metric} definition={definition} />}
      {answer.function && (
        <MetricEvidence
          result={answer.function.result}
          definition={definition}
          name={definition.functions?.[answer.function.function]?.label || answer.function.function}
        />
      )}
      {answer.object && <Facts item={answer.object} definition={definition} />}
      {answer.related && (
        <section className="grid gap-2" aria-label="关联对象">
          <h4 className="font-medium">
            {definition.relations?.[answer.related.relation]?.label || answer.related.relation} ·{' '}
            {answer.related.objects.length} 个关联对象
          </h4>
          {!answer.related.complete && <p className={status}>关联结果覆盖不足</p>}
          {answer.related.objects.map((item) => (
            <Facts key={item.object_type + JSON.stringify(item.key)} item={item} definition={definition} />
          ))}
        </section>
      )}
      {answer.rule && (
        <div className="grid gap-1">
          <p>
            {definition.rules?.[answer.rule.rule]?.label || answer.rule.rule} · {ruleOutcomes[answer.rule.outcome]}
          </p>
          <p className={status}>观察时间 · {answer.rule.observed_at}</p>
          <Facts item={answer.rule.evidence} definition={definition} />
        </div>
      )}
      {answer.citations.length > 0 && (
        <section className="grid gap-2" aria-label="文档原文">
          <h4 className="font-medium">文档原文</h4>
          {answer.citations.map((citation) => (
            <figure className={styles.citation} key={citation.chunk_id + ':' + citation.evidence.start_char}>
              <figcaption>
                <Link className={textLink} href={buildChunkPreviewDocumentHref(citation.document_id)}>
                  {citation.filename}
                </Link>
                {citation.page !== null && <> · 第 {citation.page} 页</>}
                {citation.applicability === 'pending' && <span className="text-muted-foreground"> · 适用性待确认</span>}
              </figcaption>
              <blockquote className="whitespace-pre-wrap break-words border-s-2 pl-2">
                {citation.evidence.quote}
              </blockquote>
              {Object.entries(citation.metadata).map(([id, values]) => (
                <p className="break-words text-muted-foreground" key={id}>
                  {definition.document_metadata?.[id]?.label || id} · {values.join('、')}
                </p>
              ))}
            </figure>
          ))}
        </section>
      )}
      {answer.conflicts.length > 0 && (
        <section aria-label="证据冲突">
          <h4 className="font-medium">证据冲突</h4>
          <ul className="list-disc pl-4 text-destructive">
            {answer.conflicts.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </section>
      )}
      {answer.unavailable.length > 0 && (
        <section aria-label="待核验结果">
          <h4 className="font-medium">待核验结果</h4>
          <ul className="list-disc pl-4 text-muted-foreground">
            {answer.unavailable.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </section>
      )}
      {answer.plan.action_id && definition.actions?.[answer.plan.action_id] && (
        <p>
          建议动作 · {definition.actions[answer.plan.action_id].label || answer.plan.action_id}。请在下方预演并确认。
        </p>
      )}
    </div>
  )
}

function PublishedActions({
  definition,
  actions,
  ontologyId,
  versionId,
  edoHeaders,
  run,
}: {
  definition: PublishedDefinition
  actions: Record<string, ActionDefinition>
  ontologyId: string
  versionId: string
  edoHeaders?: EnterpriseOntologyHeaders
  run: Run
}) {
  const [selected, setSelected] = useState('')
  const action = actions[selected]
  const object = action ? definition.object_types[action.object_type] : undefined
  return (
    <section className={styles.operationCard} aria-label="业务动作">
      <h3 className={styles.cardHeading}>
        <span className={styles.sectionIcon} data-tone="action" aria-hidden="true">
          <Zap />
        </span>
        业务动作
      </h3>
      <label className={field}>
        已发布动作
        <select className={select} value={selected} onChange={(event) => setSelected(event.target.value)}>
          <option value="">选择业务动作</option>
          {Object.entries(actions).map(([id, item]) => (
            <option key={id} value={id}>
              {item.label || id}
            </option>
          ))}
        </select>
      </label>
      {action && object && (
        <OntologyActionForm
          key={selected}
          proposal={{
            ontology_id: ontologyId,
            version_id: versionId,
            action_id: selected,
            label: action.label || selected,
            target: action.target,
            approval_required: action.approval_required,
            key_fields: Object.fromEntries(
              object.key.map((id) => {
                const property = object.properties[id]
                return [id, typeof property === 'string' ? id : property.label || id]
              }),
            ),
            parameter_fields: Object.fromEntries(
              Object.entries(action.parameters).map(([id, parameter]) => [
                id,
                { label: parameter.label || id, required: parameter.required === true },
              ]),
            ),
            key: {},
            parameters: {},
          }}
          edoHeaders={edoHeaders}
          run={run}
        />
      )}
    </section>
  )
}
