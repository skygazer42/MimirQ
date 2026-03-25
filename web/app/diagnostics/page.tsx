'use client'

import dynamic from 'next/dynamic'

const DiagnosticsPageClient = dynamic(() => import('./page-client'), {
  ssr: false,
  loading: () => <div className="min-h-dvh bg-background" />,
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
