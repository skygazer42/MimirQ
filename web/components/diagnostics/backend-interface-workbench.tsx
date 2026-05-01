'use client'

import { useState, type ComponentType, type ReactNode } from 'react'
import { Activity, Copy, Download, FileText, GitBranch, Network, Play, ShieldCheck, Sparkles } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import {
  datasetApi,
  documentApi,
  industryRulesApi,
  kgApi,
  lineageApi,
  rtbfApi,
  type DatasetAnalysisFilters,
  type KGNetworkEdge,
  type KGNetworkRequest,
} from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn } from '@/lib/utils'

const CARD_CLASS = 'rounded-lg border-border/70 shadow-none transition-none hover:translate-y-0 hover:shadow-none'
const CARD_HEADER_CLASS = 'space-y-0 px-3 py-2.5'
const CARD_CONTENT_CLASS = 'px-3 pb-3 pt-0'
const FIELD_HINT = 'text-[11px] leading-relaxed text-muted-foreground'
const SMALL_BUTTON = 'h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold'
const JSON_PANEL =
  'max-h-[320px] overflow-auto rounded-md border border-border/60 bg-muted/20 p-3 text-xs whitespace-pre-wrap break-words'

type ResultState = {
  title: string
  endpoint: string
  payload: unknown
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function parseJson<T>(raw: string, fallback: T): T {
  const text = String(raw || '').trim()
  if (!text) return fallback
  return JSON.parse(text) as T
}

function requireText(value: string, label: string): string {
  const trimmed = String(value || '').trim()
  if (!trimmed) {
    throw new Error(`请先填写 ${label}`)
  }
  return trimmed
}

async function copyToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    toast.success('已复制')
  } catch (err) {
    console.error('Copy failed', err)
    toast.error('复制失败')
  }
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function downloadText(content: string, filename: string, type: string): void {
  downloadBlob(new Blob([content], { type }), filename)
}

function buildSafeFilename(value: string, fallback: string): string {
  const raw = String(value || '').trim() || fallback
  return raw.replace(/[^\w.-]+/g, '_').slice(0, 96) || fallback
}

export function BackendInterfaceWorkbench() {
  const [runningKey, setRunningKey] = useState<string | null>(null)
  const [result, setResult] = useState<ResultState | null>(null)

  const [analysisDatasetId, setAnalysisDatasetId] = useState('')
  const [analysisRuleset, setAnalysisRuleset] = useState('industrial_control')
  const [analysisCategory, setAnalysisCategory] = useState('')
  const [analysisPolarity, setAnalysisPolarity] = useState('')
  const [analysisLimit, setAnalysisLimit] = useState(20)
  const [analysisTaskId, setAnalysisTaskId] = useState('')

  const [networkEdgesJson, setNetworkEdgesJson] = useState(
    prettyJson([
      { source: 'A', target: 'B', weight: 1 },
      { source: 'B', target: 'C', weight: 1 },
      { source: 'A', target: 'D', weight: 0.8 },
    ])
  )
  const [networkStartId, setNetworkStartId] = useState('A')
  const [networkTargetId, setNetworkTargetId] = useState('C')
  const [networkNodeId, setNetworkNodeId] = useState('B')
  const [networkAlgorithm, setNetworkAlgorithm] = useState<'degree' | 'pagerank'>('degree')

  const [rulesetName, setRulesetName] = useState('industrial_control')
  const [rulesetQuery, setRulesetQuery] = useState('PLC 报警如何排查？')
  const [glossaryJson, setGlossaryJson] = useState(prettyJson({ PLC: ['可编程逻辑控制器'], SCADA: ['监控与数据采集'] }))
  const [patternsJson, setPatternsJson] = useState(prettyJson([]))
  const [intentsJson, setIntentsJson] = useState(prettyJson([]))

  const [lineageChunkId, setLineageChunkId] = useState('')
  const [lineageRequestId, setLineageRequestId] = useState('')

  const [rtbfAccountId, setRtbfAccountId] = useState('')
  const [rtbfDryRun, setRtbfDryRun] = useState(true)
  const [rtbfMaxDocs, setRtbfMaxDocs] = useState(100)
  const [rtbfMaxRetries, setRtbfMaxRetries] = useState(1)
  const [rtbfTicketId, setRtbfTicketId] = useState('')

  const [cleanDocxDocumentId, setCleanDocxDocumentId] = useState('')

  async function runAction(key: string, title: string, endpoint: string, fn: () => Promise<unknown>): Promise<void> {
    setRunningKey(key)
    try {
      const payload = await fn()
      setResult({ title, endpoint, payload })
      toast.success(`${title} 完成`)
    } catch (err) {
      toast.error(formatApiError(err, `${title} 失败`))
    } finally {
      setRunningKey(null)
    }
  }

  function analysisFilters(): DatasetAnalysisFilters {
    return {
      category: analysisCategory.trim() || undefined,
      feedback_polarity: analysisPolarity === 'all' ? undefined : analysisPolarity || undefined,
    }
  }

  function networkRequest(): KGNetworkRequest {
    const edges = parseJson<KGNetworkEdge[]>(networkEdgesJson, [])
    return {
      edges,
      start_id: networkStartId.trim() || undefined,
      target_id: networkTargetId.trim() || undefined,
      node_id: networkNodeId.trim() || undefined,
      algorithm: networkAlgorithm,
      max_hops: 3,
      top_k: 10,
    }
  }

  const busy = (key: string) => runningKey === key
  const resultJson = prettyJson(result?.payload ?? { message: '尚未调用接口' })

  return (
    <Card className={cn(CARD_CLASS, 'md:col-span-2')}>
      <CardHeader className={cn(CARD_HEADER_CLASS, 'flex flex-row items-center justify-between space-y-0')}>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Sparkles className="h-4 w-4 text-info" aria-hidden="true" />
          后端接口闭环工作台
        </CardTitle>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 rounded-lg"
          onClick={async () => copyToClipboard(resultJson)}
          title="复制当前结果 JSON"
          aria-label="复制当前结果 JSON"
        >
          <Copy className="h-4 w-4" />
        </Button>
      </CardHeader>
      <CardContent className={cn(CARD_CONTENT_CLASS, 'space-y-4')}>
        <p className={FIELD_HINT}>
          覆盖当前后端新增但容易缺 UI 入口的接口域：dataset analysis、KG network、industry rules、lineage、RTBF、clean DOCX。
          这里保留为联调与验收入口；对应能力也已挂到数据集、图谱、设置/治理、历史和文档详情业务页面。
        </p>

        <Tabs defaultValue="analysis" className="w-full">
          <TabsList className="h-auto flex-wrap justify-start rounded-xl border border-border/60 bg-muted/30 p-1">
            <TabsTrigger value="analysis" className="text-xs">Dataset Analysis</TabsTrigger>
            <TabsTrigger value="kg" className="text-xs">KG Network</TabsTrigger>
            <TabsTrigger value="rules" className="text-xs">Industry Rules</TabsTrigger>
            <TabsTrigger value="lineage" className="text-xs">Lineage / RTBF</TabsTrigger>
            <TabsTrigger value="docx" className="text-xs">Clean DOCX</TabsTrigger>
          </TabsList>

          <TabsContent value="analysis" className="space-y-3">
            <div className="grid gap-3 md:grid-cols-5">
              <Field label="数据集 ID" id="analysis-dataset-id" className="md:col-span-2">
                <Input id="analysis-dataset-id" value={analysisDatasetId} onChange={(e) => setAnalysisDatasetId(e.target.value)} />
              </Field>
              <Field label="规则集" id="analysis-ruleset">
                <Input id="analysis-ruleset" value={analysisRuleset} onChange={(e) => setAnalysisRuleset(e.target.value)} />
              </Field>
              <Field label="反馈极性" id="analysis-polarity">
                <Select value={analysisPolarity || 'all'} onValueChange={setAnalysisPolarity}>
                  <SelectTrigger id="analysis-polarity"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部</SelectItem>
                    <SelectItem value="positive">positive</SelectItem>
                    <SelectItem value="negative">negative</SelectItem>
                    <SelectItem value="neutral">neutral</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Limit" id="analysis-limit">
                <Input id="analysis-limit" value={String(analysisLimit)} onChange={(e) => setAnalysisLimit(Number.parseInt(e.target.value || '0', 10) || 20)} inputMode="numeric" />
              </Field>
              <Field label="分类" id="analysis-category" className="md:col-span-2">
                <Input id="analysis-category" value={analysisCategory} onChange={(e) => setAnalysisCategory(e.target.value)} placeholder="可选 category" />
              </Field>
              <Field label="PNG 任务 ID" id="analysis-task-id" className="md:col-span-3">
                <Input id="analysis-task-id" value={analysisTaskId} onChange={(e) => setAnalysisTaskId(e.target.value)} placeholder="创建 PNG 导出任务后填写/粘贴" />
              </Field>
            </div>

            <div className="flex flex-wrap gap-2">
              <ActionButton icon={Activity} loading={busy('analysis-dashboard')} onClick={() => runAction('analysis-dashboard', '租户分析看板', 'GET /datasets/analysis/dashboard', () => datasetApi.getAnalysisDashboard({ feedback_polarity: analysisPolarity || undefined, limit: analysisLimit }))}>看板</ActionButton>
              <ActionButton icon={FileText} loading={busy('analysis-summary')} onClick={() => runAction('analysis-summary', '数据集分析摘要', 'GET /datasets/{id}/analysis/summary', () => datasetApi.getAnalysisSummary(requireText(analysisDatasetId, '数据集 ID'), analysisFilters()))}>摘要</ActionButton>
              <ActionButton icon={FileText} loading={busy('analysis-examples')} onClick={() => runAction('analysis-examples', '数据集分析样例', 'GET /datasets/{id}/analysis/examples', () => datasetApi.getAnalysisExamples(requireText(analysisDatasetId, '数据集 ID'), { ...analysisFilters(), limit: analysisLimit }))}>样例</ActionButton>
              <ActionButton icon={Sparkles} loading={busy('analysis-suggestions')} onClick={() => runAction('analysis-suggestions', '规则建议', 'GET /datasets/{id}/analysis/rule-suggestions', () => datasetApi.getAnalysisRuleSuggestions(requireText(analysisDatasetId, '数据集 ID'), { ruleset: requireText(analysisRuleset, '规则集'), feedback_polarity: analysisPolarity || undefined, limit: analysisLimit }))}>规则建议</ActionButton>
              <ActionButton icon={ShieldCheck} loading={busy('analysis-writeback')} onClick={() => runAction('analysis-writeback', '术语写回', 'POST /datasets/{id}/analysis/glossary-writeback', () => datasetApi.writebackAnalysisGlossary(requireText(analysisDatasetId, '数据集 ID'), { ...analysisFilters(), ruleset: requireText(analysisRuleset, '规则集'), limit: analysisLimit }))}>写回术语</ActionButton>
              <ActionButton icon={Download} loading={busy('analysis-json')} onClick={() => runAction('analysis-json', '导出分析 JSON', 'GET /datasets/{id}/analysis/export.json', async () => {
                const payload = await datasetApi.exportAnalysisJson(requireText(analysisDatasetId, '数据集 ID'), analysisFilters())
                downloadText(prettyJson(payload), `${buildSafeFilename(analysisDatasetId, 'dataset')}.analysis.json`, 'application/json;charset=utf-8')
                return payload
              })}>导出 JSON</ActionButton>
              <ActionButton icon={Download} loading={busy('analysis-jsonl')} onClick={() => runAction('analysis-jsonl', '导出分析 JSONL', 'GET /datasets/{id}/analysis/export.jsonl', async () => {
                const payload = await datasetApi.exportAnalysisJsonl(requireText(analysisDatasetId, '数据集 ID'), analysisFilters())
                downloadText(payload, `${buildSafeFilename(analysisDatasetId, 'dataset')}.analysis.jsonl`, 'application/x-ndjson;charset=utf-8')
                return { bytes: payload.length }
              })}>导出 JSONL</ActionButton>
              <ActionButton icon={Download} loading={busy('analysis-html')} onClick={() => runAction('analysis-html', '导出分析 HTML', 'GET /datasets/{id}/analysis/report.html', async () => {
                const payload = await datasetApi.exportAnalysisHtmlReport(requireText(analysisDatasetId, '数据集 ID'), analysisFilters())
                downloadText(payload, `${buildSafeFilename(analysisDatasetId, 'dataset')}.analysis.html`, 'text/html;charset=utf-8')
                return { bytes: payload.length }
              })}>导出 HTML</ActionButton>
              <ActionButton icon={Play} loading={busy('analysis-png-task')} onClick={() => runAction('analysis-png-task', '创建 PNG 导出任务', 'POST /datasets/{id}/analysis/export.png', async () => {
                const payload = await datasetApi.createAnalysisPngExportTask(requireText(analysisDatasetId, '数据集 ID'), analysisFilters())
                const taskId = typeof payload?.task_id === 'string' ? payload.task_id : typeof payload?.id === 'string' ? payload.id : ''
                if (taskId) setAnalysisTaskId(taskId)
                return payload
              })}>PNG 任务</ActionButton>
              <ActionButton icon={Activity} loading={busy('analysis-png-status')} onClick={() => runAction('analysis-png-status', '查询 PNG 任务', 'GET /datasets/{id}/analysis/export-tasks/{task_id}', () => datasetApi.getAnalysisPngExportTask(requireText(analysisDatasetId, '数据集 ID'), requireText(analysisTaskId, 'PNG 任务 ID')))}>查任务</ActionButton>
              <ActionButton icon={Download} loading={busy('analysis-png-result')} onClick={() => runAction('analysis-png-result', '下载 PNG 结果', 'GET /datasets/{id}/analysis/export-tasks/{task_id}/result.png', async () => {
                const blob = await datasetApi.getAnalysisPngExportResult(requireText(analysisDatasetId, '数据集 ID'), requireText(analysisTaskId, 'PNG 任务 ID'))
                downloadBlob(blob, `${buildSafeFilename(analysisDatasetId, 'dataset')}.analysis.png`)
                return { bytes: blob.size, type: blob.type }
              })}>下载 PNG</ActionButton>
            </div>
          </TabsContent>

          <TabsContent value="kg" className="space-y-3">
            <div className="grid gap-3 lg:grid-cols-3">
              <Field label="Edges JSON" id="network-edges" className="lg:col-span-2">
                <Textarea id="network-edges" value={networkEdgesJson} onChange={(e) => setNetworkEdgesJson(e.target.value)} className="min-h-[180px] font-mono text-xs" />
              </Field>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
                <Field label="Start ID" id="network-start"><Input id="network-start" value={networkStartId} onChange={(e) => setNetworkStartId(e.target.value)} /></Field>
                <Field label="Target ID" id="network-target"><Input id="network-target" value={networkTargetId} onChange={(e) => setNetworkTargetId(e.target.value)} /></Field>
                <Field label="Node ID" id="network-node"><Input id="network-node" value={networkNodeId} onChange={(e) => setNetworkNodeId(e.target.value)} /></Field>
                <Field label="Centrality" id="network-algo">
                  <Select value={networkAlgorithm} onValueChange={(value) => setNetworkAlgorithm(value as 'degree' | 'pagerank')}>
                    <SelectTrigger id="network-algo"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="degree">degree</SelectItem>
                      <SelectItem value="pagerank">pagerank</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <ActionButton icon={Network} loading={busy('kg-hop')} onClick={() => runAction('kg-hop', 'K-hop 邻居', 'POST /kg/network/k_hop_neighbors', () => kgApi.getKHopNeighbors(networkRequest()))}>K-hop</ActionButton>
              <ActionButton icon={Network} loading={busy('kg-shortest')} onClick={() => runAction('kg-shortest', '最短路径', 'POST /kg/network/shortest_path', () => kgApi.getShortestPath(networkRequest()))}>最短路径</ActionButton>
              <ActionButton icon={Network} loading={busy('kg-paths')} onClick={() => runAction('kg-paths', '路径枚举', 'POST /kg/network/paths_between', () => kgApi.getPathsBetween(networkRequest()))}>路径枚举</ActionButton>
              <ActionButton icon={Network} loading={busy('kg-centrality')} onClick={() => runAction('kg-centrality', '中心性', 'POST /kg/network/centrality', () => kgApi.getCentrality(networkRequest()))}>中心性</ActionButton>
              <ActionButton icon={Network} loading={busy('kg-community')} onClick={() => runAction('kg-community', '社区归属', 'POST /kg/network/community_of', () => kgApi.getCommunityOf(networkRequest()))}>社区归属</ActionButton>
              <ActionButton icon={Network} loading={busy('kg-component')} onClick={() => runAction('kg-component', '连通分量', 'POST /kg/network/connected_component', () => kgApi.getConnectedComponent(networkRequest()))}>连通分量</ActionButton>
            </div>
          </TabsContent>

          <TabsContent value="rules" className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Ruleset" id="ruleset-name">
                <Input id="ruleset-name" value={rulesetName} onChange={(e) => setRulesetName(e.target.value)} />
              </Field>
              <Field label="Preview Query" id="ruleset-query">
                <Input id="ruleset-query" value={rulesetQuery} onChange={(e) => setRulesetQuery(e.target.value)} />
              </Field>
            </div>
            <div className="grid gap-3 lg:grid-cols-3">
              <Field label="Glossary JSON" id="rules-glossary">
                <Textarea id="rules-glossary" value={glossaryJson} onChange={(e) => setGlossaryJson(e.target.value)} className="min-h-[150px] font-mono text-xs" />
              </Field>
              <Field label="Patterns JSON" id="rules-patterns">
                <Textarea id="rules-patterns" value={patternsJson} onChange={(e) => setPatternsJson(e.target.value)} className="min-h-[150px] font-mono text-xs" />
              </Field>
              <Field label="Intents JSON" id="rules-intents">
                <Textarea id="rules-intents" value={intentsJson} onChange={(e) => setIntentsJson(e.target.value)} className="min-h-[150px] font-mono text-xs" />
              </Field>
            </div>
            <div className="flex flex-wrap gap-2">
              <ActionButton icon={FileText} loading={busy('rules-list')} onClick={() => runAction('rules-list', '规则集列表', 'GET /industry-rules/rulesets', async () => {
                const payload = await industryRulesApi.listRulesets()
                const first = payload.rulesets?.[0]?.name
                if (first && !rulesetName.trim()) setRulesetName(first)
                return payload
              })}>列表</ActionButton>
              <ActionButton icon={FileText} loading={busy('rules-get')} onClick={() => runAction('rules-get', '规则集详情', 'GET /industry-rules/rulesets/{name}', () => industryRulesApi.getRuleset(requireText(rulesetName, 'Ruleset')))}>详情</ActionButton>
              <ActionButton icon={Sparkles} loading={busy('rules-preview')} onClick={() => runAction('rules-preview', '规则改写预览', 'POST /industry-rules/preview-rewrite', () => industryRulesApi.previewRewrite({ ruleset: requireText(rulesetName, 'Ruleset'), query: requireText(rulesetQuery, 'Preview Query') }))}>改写预览</ActionButton>
              <ActionButton icon={ShieldCheck} loading={busy('rules-glossary')} onClick={() => runAction('rules-glossary', '更新 glossary', 'PUT /industry-rules/rulesets/{name}/glossary', () => industryRulesApi.updateGlossary(requireText(rulesetName, 'Ruleset'), { glossary: parseJson<Record<string, string[]>>(glossaryJson, {}) }))}>更新 glossary</ActionButton>
              <ActionButton icon={ShieldCheck} loading={busy('rules-patterns')} onClick={() => runAction('rules-patterns', '更新 patterns', 'PUT /industry-rules/rulesets/{name}/patterns', () => industryRulesApi.updatePatterns(requireText(rulesetName, 'Ruleset'), { patterns: parseJson<Array<Record<string, any>>>(patternsJson, []) }))}>更新 patterns</ActionButton>
              <ActionButton icon={ShieldCheck} loading={busy('rules-intents')} onClick={() => runAction('rules-intents', '更新 intents', 'PUT /industry-rules/rulesets/{name}/intents', () => industryRulesApi.updateIntents(requireText(rulesetName, 'Ruleset'), { intents: parseJson<Array<Record<string, any>>>(intentsJson, []) }))}>更新 intents</ActionButton>
            </div>
          </TabsContent>

          <TabsContent value="lineage" className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Chunk ID" id="lineage-chunk"><Input id="lineage-chunk" value={lineageChunkId} onChange={(e) => setLineageChunkId(e.target.value)} /></Field>
              <Field label="Answer Request ID" id="lineage-answer"><Input id="lineage-answer" value={lineageRequestId} onChange={(e) => setLineageRequestId(e.target.value)} /></Field>
              <Field label="RTBF Account ID" id="rtbf-account"><Input id="rtbf-account" value={rtbfAccountId} onChange={(e) => setRtbfAccountId(e.target.value)} /></Field>
              <Field label="RTBF Ticket ID" id="rtbf-ticket"><Input id="rtbf-ticket" value={rtbfTicketId} onChange={(e) => setRtbfTicketId(e.target.value)} /></Field>
              <Field label="RTBF Max Docs" id="rtbf-max-docs"><Input id="rtbf-max-docs" value={String(rtbfMaxDocs)} onChange={(e) => setRtbfMaxDocs(Number.parseInt(e.target.value || '0', 10) || 100)} inputMode="numeric" /></Field>
              <Field label="RTBF Max Retries" id="rtbf-max-retries"><Input id="rtbf-max-retries" value={String(rtbfMaxRetries)} onChange={(e) => setRtbfMaxRetries(Number.parseInt(e.target.value || '0', 10) || 1)} inputMode="numeric" /></Field>
            </div>
            <div className="flex items-center gap-2 rounded-xl border border-border/60 bg-muted/30 p-3">
              <Switch checked={rtbfDryRun} onCheckedChange={setRtbfDryRun} id="rtbf-dry-run" />
              <Label htmlFor="rtbf-dry-run" className="text-xs font-medium">
                Dry-run 模式（默认开启，关闭后会执行级联删除）
              </Label>
            </div>
            <div className="flex flex-wrap gap-2">
              <ActionButton icon={GitBranch} loading={busy('lineage-chunk')} onClick={() => runAction('lineage-chunk', 'Chunk Lineage', 'GET /lineage/chunk/{chunk_id}', () => lineageApi.getChunkLineage(requireText(lineageChunkId, 'Chunk ID')))}>Chunk 血缘</ActionButton>
              <ActionButton icon={GitBranch} loading={busy('lineage-answer')} onClick={() => runAction('lineage-answer', 'Answer Lineage', 'GET /lineage/answer/{request_id}', () => lineageApi.getAnswerLineage(requireText(lineageRequestId, 'Answer Request ID')))}>Answer 血缘</ActionButton>
              <ActionButton icon={ShieldCheck} loading={busy('rtbf-request')} onClick={() => runAction('rtbf-request', 'RTBF 请求', 'POST /rtbf/request', () => rtbfApi.request({ subject_account_id: requireText(rtbfAccountId, 'RTBF Account ID'), dry_run: rtbfDryRun, max_docs: rtbfMaxDocs, max_retries: rtbfMaxRetries }))}>RTBF 请求</ActionButton>
              <ActionButton icon={ShieldCheck} loading={busy('rtbf-status')} onClick={() => runAction('rtbf-status', 'RTBF 状态', 'GET /rtbf/status/{ticket_id}', () => rtbfApi.getStatus(requireText(rtbfTicketId, 'RTBF Ticket ID')))}>RTBF 状态</ActionButton>
            </div>
          </TabsContent>

          <TabsContent value="docx" className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Document ID" id="clean-docx-document-id">
                <Input id="clean-docx-document-id" value={cleanDocxDocumentId} onChange={(e) => setCleanDocxDocumentId(e.target.value)} />
              </Field>
            </div>
            <ActionButton icon={Download} loading={busy('clean-docx')} onClick={() => runAction('clean-docx', '下载清洗版 DOCX', 'GET /documents/{id}/clean-docx', async () => {
              const documentId = requireText(cleanDocxDocumentId, 'Document ID')
              const blob = await documentApi.cleanDocx(documentId)
              downloadBlob(blob, `${buildSafeFilename(documentId, 'document')}.clean.docx`)
              return { bytes: blob.size, type: blob.type }
            })}>下载清洗版 DOCX</ActionButton>
          </TabsContent>
        </Tabs>

        <div className="space-y-2 rounded-xl border border-border/70 bg-muted/20 p-3">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="text-xs font-semibold text-foreground">{result?.title || '调用结果'}</div>
              <div className="mt-0.5 font-mono text-[11px] text-muted-foreground">{result?.endpoint || '等待运行接口'}</div>
            </div>
            <Button variant="ghost" size="sm" className="h-7 px-2" onClick={async () => copyToClipboard(resultJson)}>
              <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              复制
            </Button>
          </div>
          <pre className={JSON_PANEL}>{resultJson}</pre>
        </div>
      </CardContent>
    </Card>
  )
}

function Field({
  label,
  id,
  className,
  children,
}: Readonly<{
  label: string
  id: string
  className?: string
  children: ReactNode
}>) {
  return (
    <div className={cn('space-y-1.5', className)}>
      <Label htmlFor={id} className="text-[11px] font-semibold text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  )
}

function ActionButton({
  icon: Icon,
  loading,
  children,
  onClick,
}: Readonly<{
  icon: ComponentType<{ className?: string }>
  loading?: boolean
  children: ReactNode
  onClick: () => void
}>) {
  return (
    <Button type="button" variant="outline" size="sm" className={SMALL_BUTTON} onClick={onClick} disabled={loading}>
      <Icon className={cn('h-3.5 w-3.5', loading && 'animate-pulse')} aria-hidden="true" />
      {children}
    </Button>
  )
}
