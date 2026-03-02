'use client'

import { useEffect, useMemo, useState } from 'react'
import { BarChart3, Download, GitCompare, PlayCircle, RefreshCcw, Trophy } from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { formatApiError } from '@/lib/api-errors'
import { datasetApi, evaluationApi } from '@/lib/api-client'
import type { Dataset, RegressionRun, RegressionRunCreate, RagasRegressionRunDiffResponse } from '@/types'

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function sanitizeFilename(name: string): string {
  const trimmed = String(name || '').trim()
  const base = trimmed || 'retrieval-ablations'
  return base.replace(/[\\/:*?"<>|]+/g, '_')
}

function downloadJson(value: unknown, filename: string): void {
  const content = JSON.stringify(value ?? {}, null, 2)
  const blob = new Blob([content], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function toNumber(value: any): number | null {
  if (value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

const RAGAS_METRIC_OPTIONS = [
  { key: 'faithfulness', label: 'Faithfulness' },
  { key: 'response_relevancy', label: 'Response Relevancy' },
  { key: 'context_precision', label: 'Context Precision' },
] as const

const RETRIEVAL_MODE_OPTIONS = [
  { key: 'hybrid', label: 'hybrid' },
  { key: 'vector', label: 'vector' },
  { key: 'keyword', label: 'keyword' },
  { key: 'mmr', label: 'mmr' },
] as const

const LEADERBOARD_METRIC_OPTIONS = [
  { key: 'retrieval_mrr', label: 'retrieval_mrr' },
  { key: 'retrieval_recall', label: 'retrieval_recall' },
  { key: 'retrieval_ndcg_at_10', label: 'retrieval_ndcg_at_10' },
  { key: 'retrieval_ndcg_at_20', label: 'retrieval_ndcg_at_20' },
  { key: 'faithfulness_det', label: 'faithfulness_det' },
  { key: 'refusal_correctness', label: 'refusal_correctness' },
] as const

function _stableId(val: unknown): string {
  const s = String(val || '').trim()
  return s
}

export function RetrievalAblationsPage() {
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetId, setDatasetId] = useState('')

  const [runsLoading, setRunsLoading] = useState(false)
  const [runs, setRuns] = useState<RegressionRun[]>([])
  const [selectedBaseRunId, setSelectedBaseRunId] = useState('')
  const [selectedTargetRunId, setSelectedTargetRunId] = useState('')

  const [leaderboardMetricKey, setLeaderboardMetricKey] = useState<string>('retrieval_mrr')
  const [leaderboardLoading, setLeaderboardLoading] = useState(false)
  const [leaderboard, setLeaderboard] = useState<any | null>(null)

  const [diffLoading, setDiffLoading] = useState(false)
  const [diff, setDiff] = useState<RagasRegressionRunDiffResponse | null>(null)

  // Run config (ablation knobs)
  const [retrievalOnly, setRetrievalOnly] = useState(true)
  const [metricKeys, setMetricKeys] = useState<string[]>(['faithfulness', 'response_relevancy'])
  const [maxCases, setMaxCases] = useState(50)
  const [skipEmptyContexts, setSkipEmptyContexts] = useState(true)

  const [topK, setTopK] = useState(20)
  const [scoreThreshold, setScoreThreshold] = useState(0.0)
  const [retrievalMode, setRetrievalMode] = useState('hybrid')
  const [alpha, setAlpha] = useState(0.6)
  const [enableWeightRerank, setEnableWeightRerank] = useState(true)
  const [vectorWeight, setVectorWeight] = useState(0.6)
  const [keywordWeight, setKeywordWeight] = useState(0.4)
  const [mmrLambda, setMmrLambda] = useState(0.7)
  const [enableReranker, setEnableReranker] = useState(false)
  const [rerankerProvider, setRerankerProvider] = useState('llm')
  const [rerankerTopN, setRerankerTopN] = useState(20)

  const diffJson = useMemo(() => prettyJson(diff ?? { hint: '选择 base/target runs 并生成 diff' }), [diff])

  const runsByDataset = useMemo(() => {
    const ds = datasetId.trim()
    if (!ds) return runs
    return (runs || []).filter((r) => String(r?.dataset_id || '') === ds)
  }, [runs, datasetId])

  // Keep selection stable when dataset filter changes.
  useEffect(() => {
    if (!datasetId.trim()) return
    const items = runsByDataset || []
    const hasBase = items.some((r) => _stableId(r.id) === _stableId(selectedBaseRunId))
    const hasTarget = items.some((r) => _stableId(r.id) === _stableId(selectedTargetRunId))
    if (!hasBase) setSelectedBaseRunId(items?.[0]?.id || '')
    if (!hasTarget) setSelectedTargetRunId(items?.[0]?.id || '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, runsByDataset])

  async function loadDatasets(): Promise<void> {
    setDatasetsLoading(true)
    try {
      const res = await datasetApi.list({ limit: 200 })
      const items = Array.isArray(res.items) ? res.items : []
      setDatasets(items)
      if (!datasetId && items?.[0]?.id) setDatasetId(items[0].id)
    } catch (err) {
      toast.error(formatApiError(err, '加载数据集失败'))
    } finally {
      setDatasetsLoading(false)
    }
  }

  async function refreshRuns(): Promise<void> {
    setRunsLoading(true)
    try {
      const res = await evaluationApi.listRegressionRuns({ limit: 80 })
      const items = Array.isArray(res.items) ? (res.items as RegressionRun[]) : []
      setRuns(items)
      if (!selectedBaseRunId && items?.[0]?.id) setSelectedBaseRunId(items[0].id)
      if (!selectedTargetRunId && items?.[0]?.id) setSelectedTargetRunId(items[0].id)
    } catch (err) {
      toast.error(formatApiError(err, '拉取 runs 失败'))
    } finally {
      setRunsLoading(false)
    }
  }

  async function refreshLeaderboard(): Promise<void> {
    const ds = datasetId.trim()
    if (!ds) {
      toast.error('请选择 dataset')
      return
    }
    setLeaderboardLoading(true)
    try {
      const res = await evaluationApi.getRegressionRunLeaderboard({
        dataset_id: ds,
        metric_key: leaderboardMetricKey,
        limit: 50,
        include_incomplete: false,
      })
      setLeaderboard(res as any)
    } catch (err) {
      toast.error(formatApiError(err, '拉取 leaderboard 失败'))
    } finally {
      setLeaderboardLoading(false)
    }
  }

  async function runAblation(): Promise<void> {
    const ds = datasetId.trim()
    if (!ds) {
      toast.error('请选择 dataset')
      return
    }
    const payload: RegressionRunCreate = {
      dataset_id: ds,
      metrics: retrievalOnly ? [] : metricKeys,
      skip_empty_contexts: Boolean(skipEmptyContexts),
      max_cases: Math.max(1, Math.min(maxCases, 500)),
      top_k: Math.max(1, Math.min(topK, 50)),
      score_threshold: Math.max(0, Math.min(scoreThreshold, 1)),
      retrieval_mode: retrievalMode,
      alpha: Math.max(0, Math.min(alpha, 1)),
      enable_weight_rerank: Boolean(enableWeightRerank),
      vector_weight: Math.max(0, Math.min(vectorWeight, 1)),
      keyword_weight: Math.max(0, Math.min(keywordWeight, 1)),
      mmr_lambda: Math.max(0, Math.min(mmrLambda, 1)),
      enable_reranker: Boolean(enableReranker),
      reranker_provider: String(rerankerProvider || 'llm'),
      reranker_top_n: Math.max(1, Math.min(rerankerTopN, 200)),
    }

    try {
      const run = await evaluationApi.createRegressionRun(payload)
      toast.success('已创建 regression run')
      await refreshRuns()
      setSelectedTargetRunId(run.id)
    } catch (err) {
      toast.error(formatApiError(err, '创建 regression run 失败'))
    }
  }

  async function computeDiff(): Promise<void> {
    const baseId = String(selectedBaseRunId || '').trim()
    const targetId = String(selectedTargetRunId || '').trim()
    if (!baseId || !targetId) {
      toast.error('请选择 base 与 target')
      return
    }
    if (baseId === targetId) {
      toast.error('base 与 target 不能相同')
      return
    }
    setDiffLoading(true)
    try {
      const res = await evaluationApi.diffRegressionRuns(targetId, { base_run_id: baseId })
      setDiff(res)
      toast.success('已生成 diff')
    } catch (err) {
      toast.error(formatApiError(err, '生成 diff 失败'))
    } finally {
      setDiffLoading(false)
    }
  }

  async function exportDiffHtml(): Promise<void> {
    const baseId = String(selectedBaseRunId || '').trim()
    const targetId = String(selectedTargetRunId || '').trim()
    if (!baseId || !targetId) {
      toast.error('请选择 base 与 target')
      return
    }
    if (baseId === targetId) {
      toast.error('base 与 target 不能相同')
      return
    }

    try {
      const blob = await evaluationApi.exportRegressionRunDiffHtml(targetId, { base_run_id: baseId, redact: true })
      const name = sanitizeFilename(`regression-diff_${baseId.slice(0, 8)}_vs_${targetId.slice(0, 8)}.html`)
      downloadBlob(blob, name)
    } catch (err) {
      toast.error(formatApiError(err, '导出 HTML 失败'))
    }
  }

  useEffect(() => {
    void loadDatasets()
    void refreshRuns()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const leaderboardItems = (leaderboard as any)?.items
  const leaderboardRows: Array<{
    run_id: string
    status: string
    created_at?: string | null
    finished_at?: string | null
    metric_key: string
    metric_value?: number | null
    retrieval_config_hash?: string | null
  }> = Array.isArray(leaderboardItems) ? leaderboardItems : []

  return (
    <AppFrame>
      <PageScaffold
        title="检索消融"
        description="Regression runs：run / leaderboard / diff（用于 retrieval ablation）"
        icon={BarChart3}
        iconColor="text-indigo-600 dark:text-indigo-400"
        size="7xl"
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="gap-2 rounded-xl"
              disabled={datasetsLoading || runsLoading}
              onClick={() => {
                void loadDatasets()
                void refreshRuns()
              }}
            >
              <RefreshCcw className="w-4 h-4" />
              刷新
            </Button>
          </div>
        }
      >
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <Card className="xl:col-span-1">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <PlayCircle className="w-5 h-5" />
                Run Ablation
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>数据集</Label>
                <Select value={datasetId} onValueChange={setDatasetId} disabled={datasetsLoading || !datasets.length}>
                  <SelectTrigger className="h-9 rounded-xl">
                    <SelectValue placeholder={datasetsLoading ? '加载中...' : '选择数据集'} />
                  </SelectTrigger>
                  <SelectContent>
                    {(datasets || []).map((d) => (
                      <SelectItem key={d.id} value={d.id}>
                        {d.name || d.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="rounded-2xl border border-border bg-card/60 backdrop-blur-sm p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium">Retrieval-only</div>
                  <Switch checked={retrievalOnly} onCheckedChange={setRetrievalOnly} />
                </div>
                {!retrievalOnly && (
                  <div className="space-y-2">
                    <div className="text-xs text-muted-foreground">RAGAS metrics</div>
                    <div className="grid grid-cols-1 gap-2">
                      {RAGAS_METRIC_OPTIONS.map((opt) => {
                        const checked = metricKeys.includes(opt.key)
                        return (
                          <label key={opt.key} className="flex items-center gap-2 text-sm">
                            <Checkbox
                              checked={checked}
                              onCheckedChange={(v) => {
                                const next = new Set(metricKeys)
                                if (v) next.add(opt.key)
                                else next.delete(opt.key)
                                setMetricKeys(Array.from(next))
                              }}
                            />
                            {opt.label}
                          </label>
                        )
                      })}
                    </div>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <Label>max_cases</Label>
                    <Input
                      type="number"
                      value={maxCases}
                      onChange={(e) => setMaxCases(Number(e.target.value || 0))}
                      min={1}
                      max={500}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>top_k</Label>
                    <Input
                      type="number"
                      value={topK}
                      onChange={(e) => setTopK(Number(e.target.value || 0))}
                      min={1}
                      max={50}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>score_threshold</Label>
                    <Input
                      type="number"
                      value={scoreThreshold}
                      onChange={(e) => setScoreThreshold(Number(e.target.value || 0))}
                      min={0}
                      max={1}
                      step={0.01}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>retrieval_mode</Label>
                    <Select value={retrievalMode} onValueChange={setRetrievalMode}>
                      <SelectTrigger className="h-9 rounded-xl">
                        <SelectValue placeholder="选择" />
                      </SelectTrigger>
                      <SelectContent>
                        {RETRIEVAL_MODE_OPTIONS.map((o) => (
                          <SelectItem key={o.key} value={o.key}>
                            {o.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <Label>alpha</Label>
                    <Input
                      type="number"
                      value={alpha}
                      onChange={(e) => setAlpha(Number(e.target.value || 0))}
                      min={0}
                      max={1}
                      step={0.05}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>mmr_lambda</Label>
                    <Input
                      type="number"
                      value={mmrLambda}
                      onChange={(e) => setMmrLambda(Number(e.target.value || 0))}
                      min={0}
                      max={1}
                      step={0.05}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>vector_weight</Label>
                    <Input
                      type="number"
                      value={vectorWeight}
                      onChange={(e) => setVectorWeight(Number(e.target.value || 0))}
                      min={0}
                      max={1}
                      step={0.05}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>keyword_weight</Label>
                    <Input
                      type="number"
                      value={keywordWeight}
                      onChange={(e) => setKeywordWeight(Number(e.target.value || 0))}
                      min={0}
                      max={1}
                      step={0.05}
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between">
                  <label className="flex items-center gap-2 text-sm">
                    <Checkbox checked={skipEmptyContexts} onCheckedChange={(v) => setSkipEmptyContexts(Boolean(v))} />
                    skip_empty_contexts
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <Checkbox checked={enableWeightRerank} onCheckedChange={(v) => setEnableWeightRerank(Boolean(v))} />
                    enable_weight_rerank
                  </label>
                </div>

                <div className="rounded-xl border border-border p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium">reranker</div>
                    <Switch checked={enableReranker} onCheckedChange={setEnableReranker} />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-2">
                      <Label>provider</Label>
                      <Input value={rerankerProvider} onChange={(e) => setRerankerProvider(e.target.value)} />
                    </div>
                    <div className="space-y-2">
                      <Label>top_n</Label>
                      <Input
                        type="number"
                        value={rerankerTopN}
                        onChange={(e) => setRerankerTopN(Number(e.target.value || 0))}
                        min={1}
                        max={200}
                      />
                    </div>
                  </div>
                </div>

                <Button className="w-full gap-2 rounded-xl" onClick={() => void runAblation()}>
                  <PlayCircle className="w-4 h-4" />
                  Run
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card className="xl:col-span-2">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Trophy className="w-5 h-5" />
                Leaderboard
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div className="space-y-2">
                  <Label>metric_key</Label>
                  <Select value={leaderboardMetricKey} onValueChange={setLeaderboardMetricKey}>
                    <SelectTrigger className="h-9 rounded-xl">
                      <SelectValue placeholder="选择" />
                    </SelectTrigger>
                    <SelectContent>
                      {LEADERBOARD_METRIC_OPTIONS.map((m) => (
                        <SelectItem key={m.key} value={m.key}>
                          {m.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-end gap-2">
                  <Button
                    variant="outline"
                    className="gap-2 rounded-xl"
                    disabled={leaderboardLoading}
                    onClick={() => void refreshLeaderboard()}
                  >
                    <RefreshCcw className="w-4 h-4" />
                    刷新
                  </Button>
                </div>
              </div>

              <div className="rounded-2xl border border-border overflow-hidden">
                <div className="grid grid-cols-12 text-xs font-semibold text-muted-foreground bg-muted/40 px-3 py-2">
                  <div className="col-span-3">run_id</div>
                  <div className="col-span-2">status</div>
                  <div className="col-span-2">metric</div>
                  <div className="col-span-3">retrieval_config_hash</div>
                  <div className="col-span-2 text-right">actions</div>
                </div>
                {(leaderboardRows || []).length ? (
                  (leaderboardRows || []).map((r) => {
                    const runId = String(r.run_id || '')
                    const metricValue = toNumber(r.metric_value)
                    return (
                      <div
                        key={runId}
                        className="grid grid-cols-12 px-3 py-2 text-sm border-t border-border items-center"
                      >
                        <div className="col-span-3 font-mono text-xs truncate">{runId}</div>
                        <div className="col-span-2">{String(r.status || '')}</div>
                        <div className="col-span-2">{metricValue === null ? '-' : metricValue.toFixed(4)}</div>
                        <div className="col-span-3 font-mono text-xs truncate">{String(r.retrieval_config_hash || '')}</div>
                        <div className="col-span-2 flex items-center justify-end gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            className="rounded-xl"
                            onClick={() => setSelectedBaseRunId(runId)}
                          >
                            base
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="rounded-xl"
                            onClick={() => setSelectedTargetRunId(runId)}
                          >
                            target
                          </Button>
                        </div>
                      </div>
                    )
                  })
                ) : (
                  <div className="px-3 py-6 text-sm text-muted-foreground">
                    选择 dataset 后点击刷新以加载 leaderboard
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <Card className="xl:col-span-3">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <GitCompare className="w-5 h-5" />
                Run Diff
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label>base_run_id</Label>
                  <Select value={selectedBaseRunId} onValueChange={setSelectedBaseRunId} disabled={runsLoading}>
                    <SelectTrigger className="h-9 rounded-xl">
                      <SelectValue placeholder={runsLoading ? '加载中...' : '选择 run'} />
                    </SelectTrigger>
                    <SelectContent>
                      {(runsByDataset || []).map((r) => (
                        <SelectItem key={r.id} value={r.id}>
                          {String(r.id).slice(0, 8)} · {String(r.status || 'unknown')}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>target_run_id</Label>
                  <Select value={selectedTargetRunId} onValueChange={setSelectedTargetRunId} disabled={runsLoading}>
                    <SelectTrigger className="h-9 rounded-xl">
                      <SelectValue placeholder={runsLoading ? '加载中...' : '选择 run'} />
                    </SelectTrigger>
                    <SelectContent>
                      {(runsByDataset || []).map((r) => (
                        <SelectItem key={r.id} value={r.id}>
                          {String(r.id).slice(0, 8)} · {String(r.status || 'unknown')}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Button className="gap-2 rounded-xl" disabled={diffLoading} onClick={() => void computeDiff()}>
                  <GitCompare className="w-4 h-4" />
                  生成 diff
                </Button>
                <Button
                  variant="outline"
                  className="gap-2 rounded-xl"
                  disabled={!diff}
                  onClick={() => downloadJson(diff, sanitizeFilename('regression-run-diff.json'))}
                >
                  <Download className="w-4 h-4" />
                  导出 JSON
                </Button>
                <Button
                  variant="outline"
                  className="gap-2 rounded-xl"
                  onClick={() => void exportDiffHtml()}
                >
                  <Download className="w-4 h-4" />
                  导出 HTML
                </Button>
              </div>

              <Textarea className="min-h-[420px] font-mono text-xs" value={diffJson} readOnly />
            </CardContent>
          </Card>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}

