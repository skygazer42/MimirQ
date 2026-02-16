'use client'

import { useMemo, useState } from 'react'
import { Activity, Copy, FileJson, FileText, RefreshCcw, Timer, Hash, FileSearch } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { StatusBadge } from '@/components/ui/status-badge'
import { Textarea } from '@/components/ui/textarea'
import { useBackendHealth } from '@/hooks/use-backend-health'
import { useBackendMeta } from '@/hooks/use-backend-meta'
import { useBackendReady } from '@/hooks/use-backend-ready'
import { formatApiError } from '@/lib/api-errors'
import { ragApi } from '@/lib/api-client'
import { API_BASE_URL, API_LONG_TIMEOUT_MS, API_TIMEOUT_MS, API_V1_BASE_URL } from '@/lib/env'

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

async function copyToClipboard(text: string): Promise<void> {
  const content = text || ''

  // Prefer async clipboard API when available; fall back to execCommand when blocked.
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(content)
      toast.success('已复制到剪贴板')
      return
    }
  } catch {
    // fall through to legacy fallback
  }

  try {
    const el = document.createElement('textarea')
    el.value = content
    el.setAttribute('readonly', 'true')
    el.style.position = 'fixed'
    el.style.left = '0'
    el.style.top = '0'
    el.style.opacity = '0'
    document.body.appendChild(el)
    el.focus()
    el.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(el)
    if (!ok) throw new Error('copy failed')
    toast.success('已复制到剪贴板')
  } catch (err) {
    console.error('Copy failed:', err)
    toast.error('复制失败')
  }
}

export default function DiagnosticsPage() {
  const health = useBackendHealth()
  const meta = useBackendMeta()
  const ready = useBackendReady()

  const [probeDatasetId, setProbeDatasetId] = useState('')
  const [probeDocumentIdsRaw, setProbeDocumentIdsRaw] = useState('')
  const [probeQuery, setProbeQuery] = useState('Summarize what you know about this dataset.')
  const [probeResult, setProbeResult] = useState<any | null>(null)
  const [probeLatencyMs, setProbeLatencyMs] = useState<number | null>(null)
  const [probeRunning, setProbeRunning] = useState(false)

  const docsUrl = `${API_BASE_URL}/docs`
  const openapiUrl = `${API_BASE_URL}/openapi.json`

  const healthJson = prettyJson(health.data?.payload ?? { error: health.error ? String(health.error) : 'loading' })
  const metaJson = prettyJson(meta.data ?? { error: meta.error ? String(meta.error) : 'loading' })
  const readyJson = prettyJson(ready.data ?? { error: ready.error ? String(ready.error) : 'loading' })

  const envJson = prettyJson({
    API_BASE_URL,
    API_V1_BASE_URL,
    API_TIMEOUT_MS,
    API_LONG_TIMEOUT_MS,
  })

  const probeDocumentIds = useMemo(() => {
    const raw = (probeDocumentIdsRaw || '').trim()
    if (!raw) return []
    return raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
  }, [probeDocumentIdsRaw])

  const probeMetrics = (probeResult && typeof probeResult === 'object' ? probeResult.metrics : null) as Record<
    string,
    any
  > | null
  const probeMetricsJson = prettyJson(probeMetrics || { error: 'no probe yet' })

  async function runPromptPreviewProbe(): Promise<void> {
    const query = (probeQuery || '').trim()
    if (!query) {
      toast.error('请输入 query')
      return
    }

    const datasetId = (probeDatasetId || '').trim()
    const documentIds = probeDocumentIds

    setProbeRunning(true)
    setProbeResult(null)
    setProbeLatencyMs(null)

    const start = Date.now()
    try {
      const result = await ragApi.promptPreview({
        query,
        dataset_id: datasetId || undefined,
        document_ids: documentIds.length ? documentIds : undefined,
      })
      setProbeLatencyMs(Math.max(0, Date.now() - start))
      setProbeResult(result as any)
    } catch (err) {
      toast.error(formatApiError(err, 'RAG prompt-preview failed'))
    } finally {
      setProbeRunning(false)
    }
  }

  return (
    <PageScaffold
      title="诊断"
      description="前后端联调信息（后端健康 / 依赖就绪 / 后端元数据 / 前端 API 配置）"
      icon={Activity}
      iconColor="text-info"
      size="5xl"
      actions={
        <div className="flex items-center gap-2">
          <Button asChild variant="outline" size="sm" className="gap-2">
            <a href={docsUrl} target="_blank" rel="noreferrer" aria-label="打开后端接口文档（/docs）">
              <FileText className="h-4 w-4" aria-hidden="true" />
              /docs
            </a>
          </Button>
          <Button asChild variant="outline" size="sm" className="gap-2">
            <a href={openapiUrl} target="_blank" rel="noreferrer" aria-label="打开后端 OpenAPI（/openapi.json）">
              <FileJson className="h-4 w-4" aria-hidden="true" />
              openapi.json
            </a>
          </Button>
        </div>
      }
    >
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">Frontend Env</CardTitle>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={async () => copyToClipboard(envJson)}
              title="复制"
              aria-label="复制"
            >
              <Copy className="h-4 w-4" />
            </Button>
          </CardHeader>
          <CardContent>
            <pre className="text-xs whitespace-pre-wrap break-words">{envJson}</pre>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">Backend Meta</CardTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => meta.refetch()}
                title="刷新"
                aria-label="刷新"
              >
                <RefreshCcw className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={async () => copyToClipboard(metaJson)}
                title="复制"
                aria-label="复制"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <pre className="text-xs whitespace-pre-wrap break-words">{metaJson}</pre>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">Backend Health</CardTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => health.refetch()}
                title="刷新"
                aria-label="刷新"
              >
                <RefreshCcw className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={async () => copyToClipboard(healthJson)}
                title="复制"
                aria-label="复制"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between gap-3 pb-2">
              <StatusBadge
                status={health.isPending ? 'processing' : health.data?.payload?.ok ? 'completed' : 'failed'}
                label={
                  health.isPending ? '检查中' : health.data?.payload?.ok ? 'OK' : health.error ? '网络/服务异常' : '异常'
                }
                dense
              />
              {typeof health.data?.latencyMs === 'number' ? (
                <span className="text-xs text-muted-foreground tabular-nums">{health.data.latencyMs}ms</span>
              ) : null}
            </div>
            <pre className="text-xs whitespace-pre-wrap break-words">{healthJson}</pre>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">Deps Ready</CardTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => ready.refetch()}
                title="刷新"
                aria-label="刷新"
              >
                <RefreshCcw className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={async () => copyToClipboard(readyJson)}
                title="复制"
                aria-label="复制"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <pre className="text-xs whitespace-pre-wrap break-words">{readyJson}</pre>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">RAG Prompt Preview</CardTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => runPromptPreviewProbe()}
                disabled={probeRunning}
                title="运行 prompt-preview"
                aria-label="运行 prompt-preview"
              >
                <Activity className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={async () => copyToClipboard(probeMetricsJson)}
                disabled={!probeMetrics}
                title="复制 metrics"
                aria-label="复制 metrics"
              >
                <Copy className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-3">
              <div className="space-y-1.5">
                <Label htmlFor="probe-dataset-id">dataset_id（可选）</Label>
                <Input
                  id="probe-dataset-id"
                  value={probeDatasetId}
                  onChange={(e) => setProbeDatasetId(e.target.value)}
                  placeholder="e.g. 9b2f…"
                />
              </div>
              <div className="space-y-1.5 md:col-span-2">
                <Label htmlFor="probe-document-ids">document_ids（可选，逗号分隔）</Label>
                <Input
                  id="probe-document-ids"
                  value={probeDocumentIdsRaw}
                  onChange={(e) => setProbeDocumentIdsRaw(e.target.value)}
                  placeholder="e.g. 3f1a…, 8c02…"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="probe-query">query</Label>
              <Textarea
                id="probe-query"
                value={probeQuery}
                onChange={(e) => setProbeQuery(e.target.value)}
                placeholder="Ask a question that should retrieve evidence from the corpus"
              />
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs text-muted-foreground">
                  这个探针调用后端 `POST /api/v1/rag/prompt-preview`（不触发 LLM），用于查看 latency + token breakdown。
                </p>
                <Button variant="outline" size="sm" onClick={() => runPromptPreviewProbe()} disabled={probeRunning}>
                  {probeRunning ? '运行中…' : 'Run'}
                </Button>
              </div>
            </div>

            <StatsGrid className="xl:grid-cols-6">
              <StatCard
                icon={Timer}
                label="Latency (client)"
                value={probeLatencyMs == null ? '-' : `${probeLatencyMs}ms`}
                color="blue"
              />
              <StatCard
                icon={Activity}
                label="Retrieval"
                value={
                  typeof probeMetrics?.retrieval_elapsed_sec === 'number'
                    ? `${probeMetrics.retrieval_elapsed_sec.toFixed(3)}s`
                    : '-'
                }
                color="teal"
              />
              <StatCard
                icon={FileSearch}
                label="Context build"
                value={
                  typeof probeMetrics?.context_build_elapsed_sec === 'number'
                    ? `${probeMetrics.context_build_elapsed_sec.toFixed(3)}s`
                    : '-'
                }
                color="gray"
              />
              <StatCard
                icon={Activity}
                label="Prompt render"
                value={
                  typeof probeMetrics?.prompt_render_elapsed_sec === 'number'
                    ? `${probeMetrics.prompt_render_elapsed_sec.toFixed(3)}s`
                    : '-'
                }
                color="gray"
              />
              <StatCard
                icon={Hash}
                label="Prompt tokens"
                value={typeof probeMetrics?.prompt_tokens === 'number' ? probeMetrics.prompt_tokens : '-'}
                color="cyan"
              />
              <StatCard
                icon={Hash}
                label="Context tokens"
                value={typeof probeMetrics?.context_tokens === 'number' ? probeMetrics.context_tokens : '-'}
                color="cyan"
              />
              <StatCard
                icon={Hash}
                label="History tokens"
                value={typeof probeMetrics?.history_tokens === 'number' ? probeMetrics.history_tokens : '-'}
                color="cyan"
              />
              <StatCard
                icon={Hash}
                label="Prompt chars"
                value={typeof probeMetrics?.prompt_chars === 'number' ? probeMetrics.prompt_chars : '-'}
                color="gray"
              />
              <StatCard
                icon={Hash}
                label="Context chars"
                value={typeof probeMetrics?.context_chars === 'number' ? probeMetrics.context_chars : '-'}
                color="gray"
              />
              <StatCard
                icon={Hash}
                label="History chars"
                value={typeof probeMetrics?.history_chars === 'number' ? probeMetrics.history_chars : '-'}
                color="gray"
              />
            </StatsGrid>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-medium text-muted-foreground">Prompt Preview Metrics</p>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2"
                    onClick={async () => copyToClipboard(probeMetricsJson)}
                    disabled={!probeMetrics}
                  >
                    <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                    <span className="sr-only">复制</span>
                  </Button>
                </div>
                <pre className="text-xs whitespace-pre-wrap break-words max-h-[280px] overflow-auto rounded-md border border-border/60 p-3">
                  {probeMetricsJson}
                </pre>
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-medium text-muted-foreground">Query For Retrieval</p>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2"
                    onClick={async () => copyToClipboard(String(probeResult?.query_for_retrieval || ''))}
                    disabled={!probeResult?.query_for_retrieval}
                  >
                    <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                    <span className="sr-only">复制</span>
                  </Button>
                </div>
                <pre className="text-xs whitespace-pre-wrap break-words max-h-[280px] overflow-auto rounded-md border border-border/60 p-3">
                  {String(probeResult?.query_for_retrieval || '(not run)')}
                </pre>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </PageScaffold>
  )
}
