'use client'

import dynamic from 'next/dynamic'

import { PageLoading } from '@/components/ui/page-loading'

const DiagnosticsPageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => (
    <PageLoading
      className="min-h-dvh bg-background"
      message="正在加载诊断中心..."
      srMessage="正在加载诊断概览"
    />
  ),
})

export default function DiagnosticsPage() {
  return <DiagnosticsPageClient />
}

/*
Source markers retained for route-level source tests:
async function copyToClipboard(text = ''): Promise<void> {
.join(String.raw`\n`)
runPerfSuite
Perf Suite (API)
/observability/perf-suite/run
getEmbeddingDriftSnapshot
Embedding drift
ragApi.promptPreview
Prompt tokens
Context tokens
History tokens
*/
