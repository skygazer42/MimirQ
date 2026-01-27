'use client'

import { Activity, Copy, RefreshCcw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageScaffold } from '@/components/ui/page-scaffold'
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
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }

  // Fallback for older browsers.
  const el = document.createElement('textarea')
  el.value = text
  el.setAttribute('readonly', 'true')
  el.style.position = 'absolute'
  el.style.left = '-9999px'
  document.body.appendChild(el)
  el.select()
  document.execCommand('copy')
  document.body.removeChild(el)
}

export default function DiagnosticsPage() {
  const meta = useBackendMeta()
  const ready = useBackendReady()

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
      description="前后端联调信息（后端元数据 / 依赖就绪 / 前端 API 配置）"
      icon={Activity}
      iconColor="text-info"
      size="5xl"
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

        <Card className="md:col-span-2">
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

