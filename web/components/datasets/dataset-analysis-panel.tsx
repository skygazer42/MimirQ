'use client'

import { useState } from 'react'
import { Activity, Download, FileText, Loader2, ShieldCheck, Sparkles } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { datasetApi, type DatasetAnalysisFilters } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { detachPromise } from '@/lib/utils'

type DatasetAnalysisPanelProps = Readonly<{
  datasetId: string | null
  datasetName?: string | null
}>

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

function safeFilename(value: string | null | undefined, fallback: string): string {
  const raw = String(value || '').trim() || fallback
  return raw.replace(/[^\w.-]+/g, '_').slice(0, 96) || fallback
}

export function DatasetAnalysisPanel({ datasetId, datasetName }: DatasetAnalysisPanelProps) {
  const [category, setCategory] = useState('')
  const [polarity, setPolarity] = useState('all')
  const [ruleset, setRuleset] = useState('industrial_control')
  const [limit, setLimit] = useState(20)
  const [taskId, setTaskId] = useState('')
  const [runningKey, setRunningKey] = useState<string | null>(null)
  const [result, setResult] = useState<ResultState | null>(null)

  const hasDataset = Boolean(datasetId)
  const filters: DatasetAnalysisFilters = {
    category: category.trim() || undefined,
    feedback_polarity: polarity === 'all' ? undefined : polarity,
  }
  const safeBase = safeFilename(datasetName || datasetId, 'dataset')
  const operationResult = result ? { title: result.title, payload: { endpoint: result.endpoint, response: result.payload } } : null

  async function runAction(key: string, title: string, endpoint: string, action: () => Promise<unknown>): Promise<void> {
    setRunningKey(key)
    try {
      const payload = await action()
      setResult({ title, endpoint, payload })
      toast.success(`${title}完成`)
    } catch (error) {
      toast.error(formatApiError(error, `${title}失败`))
    } finally {
      setRunningKey(null)
    }
  }

  function datasetIdOrThrow(): string {
    const id = String(datasetId || '').trim()
    if (!id) throw new Error('缺少数据集 ID')
    return id
  }

  const actionButtonClass = 'h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold'
  const disabledDatasetAction = !hasDataset || Boolean(runningKey)

  return (
    <Panel className="space-y-4 p-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold">Dataset Analysis / 入库后分析闭环</h2>
            <Badge variant="outline" className="font-mono text-[11px]">
              OpenAPI
            </Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            直接接后端 dataset analysis 接口：摘要、样例、规则建议、术语写回和离线报告导出，不再只放在诊断工作台。
          </p>
        </div>
        <Button
          variant="outline"
          className={actionButtonClass}
          disabled={Boolean(runningKey)}
          onClick={() =>
            detachPromise(
              runAction('dashboard', '租户分析看板', 'GET /datasets/analysis/dashboard', () =>
                datasetApi.getAnalysisDashboard({ feedback_polarity: filters.feedback_polarity, limit })
              )
            )
          }
        >
          {runningKey === 'dashboard' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Activity className="h-3.5 w-3.5" />}
          看板
        </Button>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <div className="space-y-1.5">
          <Label htmlFor="dataset-analysis-ruleset" className="text-xs text-muted-foreground">
            规则集
          </Label>
          <Input id="dataset-analysis-ruleset" value={ruleset} onChange={(event) => setRuleset(event.target.value)} className="h-9" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="dataset-analysis-category" className="text-xs text-muted-foreground">
            分类过滤
          </Label>
          <Input id="dataset-analysis-category" value={category} onChange={(event) => setCategory(event.target.value)} placeholder="可选 category" className="h-9" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="dataset-analysis-polarity" className="text-xs text-muted-foreground">
            反馈极性
          </Label>
          <Select value={polarity} onValueChange={setPolarity}>
            <SelectTrigger id="dataset-analysis-polarity" className="h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部</SelectItem>
              <SelectItem value="positive">positive</SelectItem>
              <SelectItem value="negative">negative</SelectItem>
              <SelectItem value="neutral">neutral</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="dataset-analysis-limit" className="text-xs text-muted-foreground">
            Limit
          </Label>
          <Input
            id="dataset-analysis-limit"
            value={String(limit)}
            onChange={(event) => setLimit(Number.parseInt(event.target.value || '0', 10) || 20)}
            className="h-9"
            inputMode="numeric"
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          className={actionButtonClass}
          disabled={disabledDatasetAction}
          onClick={() =>
            detachPromise(
              runAction('summary', '分析摘要', 'GET /datasets/{id}/analysis/summary', () =>
                datasetApi.getAnalysisSummary(datasetIdOrThrow(), filters)
              )
            )
          }
        >
          <FileText className="h-3.5 w-3.5" />
          摘要
        </Button>
        <Button
          variant="outline"
          className={actionButtonClass}
          disabled={disabledDatasetAction}
          onClick={() =>
            detachPromise(
              runAction('examples', '分析样例', 'GET /datasets/{id}/analysis/examples', () =>
                datasetApi.getAnalysisExamples(datasetIdOrThrow(), { ...filters, limit })
              )
            )
          }
        >
          <FileText className="h-3.5 w-3.5" />
          样例
        </Button>
        <Button
          variant="outline"
          className={actionButtonClass}
          disabled={disabledDatasetAction || !ruleset.trim()}
          onClick={() =>
            detachPromise(
              runAction('suggestions', '规则建议', 'GET /datasets/{id}/analysis/rule-suggestions', () =>
                datasetApi.getAnalysisRuleSuggestions(datasetIdOrThrow(), {
                  ruleset: ruleset.trim(),
                  feedback_polarity: filters.feedback_polarity,
                  limit,
                })
              )
            )
          }
        >
          <Sparkles className="h-3.5 w-3.5" />
          规则建议
        </Button>
        <Button
          variant="outline"
          className={actionButtonClass}
          disabled={disabledDatasetAction || !ruleset.trim()}
          onClick={() =>
            detachPromise(
              runAction('writeback', '术语写回', 'POST /datasets/{id}/analysis/glossary-writeback', () =>
                datasetApi.writebackAnalysisGlossary(datasetIdOrThrow(), { ...filters, ruleset: ruleset.trim(), limit })
              )
            )
          }
        >
          <ShieldCheck className="h-3.5 w-3.5" />
          写回术语
        </Button>
        <Button
          variant="outline"
          className={actionButtonClass}
          disabled={disabledDatasetAction}
          onClick={() =>
            detachPromise(
              runAction('export-json', '导出分析 JSON', 'GET /datasets/{id}/analysis/export.json', async () => {
                const payload = await datasetApi.exportAnalysisJson(datasetIdOrThrow(), filters)
                downloadText(prettyJson(payload), `${safeBase}.analysis.json`, 'application/json;charset=utf-8')
                return payload
              })
            )
          }
        >
          <Download className="h-3.5 w-3.5" />
          JSON
        </Button>
        <Button
          variant="outline"
          className={actionButtonClass}
          disabled={disabledDatasetAction}
          onClick={() =>
            detachPromise(
              runAction('export-jsonl', '导出分析 JSONL', 'GET /datasets/{id}/analysis/export.jsonl', async () => {
                const payload = await datasetApi.exportAnalysisJsonl(datasetIdOrThrow(), filters)
                downloadText(payload, `${safeBase}.analysis.jsonl`, 'application/x-ndjson;charset=utf-8')
                return { bytes: payload.length }
              })
            )
          }
        >
          <Download className="h-3.5 w-3.5" />
          JSONL
        </Button>
        <Button
          variant="outline"
          className={actionButtonClass}
          disabled={disabledDatasetAction}
          onClick={() =>
            detachPromise(
              runAction('export-html', '导出分析 HTML', 'GET /datasets/{id}/analysis/report.html', async () => {
                const payload = await datasetApi.exportAnalysisHtmlReport(datasetIdOrThrow(), filters)
                downloadText(payload, `${safeBase}.analysis.html`, 'text/html;charset=utf-8')
                return { bytes: payload.length }
              })
            )
          }
        >
          <Download className="h-3.5 w-3.5" />
          HTML
        </Button>
        <Button
          variant="outline"
          className={actionButtonClass}
          disabled={disabledDatasetAction}
          onClick={() =>
            detachPromise(
              runAction('png-task', '创建 PNG 导出任务', 'POST /datasets/{id}/analysis/export.png', async () => {
                const payload = await datasetApi.createAnalysisPngExportTask(datasetIdOrThrow(), filters)
                const nextTaskId =
                  typeof payload.task_id === 'string'
                    ? payload.task_id
                    : typeof payload.id === 'string'
                      ? payload.id
                      : ''
                if (nextTaskId) setTaskId(nextTaskId)
                return payload
              })
            )
          }
        >
          <Sparkles className="h-3.5 w-3.5" />
          PNG 任务
        </Button>
      </div>

      <div className="flex flex-col gap-2 rounded-xl border border-border/60 bg-muted/20 p-3 lg:flex-row lg:items-end">
        <div className="min-w-0 flex-1 space-y-1.5">
          <Label htmlFor="dataset-analysis-task-id" className="text-xs text-muted-foreground">
            PNG 任务 ID
          </Label>
          <Input id="dataset-analysis-task-id" value={taskId} onChange={(event) => setTaskId(event.target.value)} className="h-9 font-mono text-xs" />
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            className={actionButtonClass}
            disabled={disabledDatasetAction || !taskId.trim()}
            onClick={() =>
              detachPromise(
                runAction('png-status', '查询 PNG 任务', 'GET /datasets/{id}/analysis/export-tasks/{task_id}', () =>
                  datasetApi.getAnalysisPngExportTask(datasetIdOrThrow(), taskId.trim())
                )
              )
            }
          >
            查任务
          </Button>
          <Button
            variant="outline"
            className={actionButtonClass}
            disabled={disabledDatasetAction || !taskId.trim()}
            onClick={() =>
              detachPromise(
                runAction('png-download', '下载 PNG 结果', 'GET /datasets/{id}/analysis/export-tasks/{task_id}/result.png', async () => {
                  const blob = await datasetApi.getAnalysisPngExportResult(datasetIdOrThrow(), taskId.trim())
                  downloadBlob(blob, `${safeBase}.analysis.png`)
                  return { bytes: blob.size, type: blob.type }
                })
              )
            }
          >
            下载 PNG
          </Button>
        </div>
      </div>

      <OperationResultPanel title="分析接口结果" result={operationResult} emptyMessage="选择上方分析动作后，这里展示执行摘要；原始响应默认收起。" />
    </Panel>
  )
}
