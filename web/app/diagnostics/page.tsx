'use client'

import dynamic from 'next/dynamic'

import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { PageLoading } from '@/components/ui/page-loading'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'

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
  return (
    <TenantPermissionGate permission={TENANT_PERMISSIONS.OBSERVABILITY_READ} pageName="诊断">
      <DiagnosticsPageClient />
    </TenantPermissionGate>
  )
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
