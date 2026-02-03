'use client'

import { Activity, Copy, FileJson, FileText, RefreshCcw } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { StatusBadge } from '@/components/ui/status-badge'
import { useBackendHealth } from '@/hooks/use-backend-health'
import { useBackendMeta } from '@/hooks/use-backend-meta'
import { useBackendReady } from '@/hooks/use-backend-ready'
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
      </div>
    </PageScaffold>
  )
}
