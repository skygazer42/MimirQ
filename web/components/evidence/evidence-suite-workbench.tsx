'use client'

import { OperationalWorkspace } from '@/components/ui/operational-workspace'
import { Button } from '@/components/ui/button'
import { Link, useRouter } from '@/i18n/navigation'
import { EvidenceSuiteWorkbenchShell } from '@/components/evidence/evidence-suite-workbench-shell'
import { useEvidenceSuiteWorkbenchState } from '@/components/evidence/use-evidence-suite-workbench-state'

export function EvidenceSuiteWorkbench({
  datasetId,
  initialFeedbackId,
}: Readonly<{
  datasetId: string
  initialFeedbackId?: string
}>) {
  const router = useRouter()
  const state = useEvidenceSuiteWorkbenchState(datasetId, { initialFeedbackId })
  return (
    <OperationalWorkspace
      title="证据库"
      icon="knowledge-base"
      mode="canvas"
      context={state.dataset?.name ?? (state.datasetLoading ? '正在读取数据集…' : '数据集未取得')}
      back={() => router.push('/datasets')}
      actions={
        <Button asChild variant="outline">
          <Link href={`/datasets/${encodeURIComponent(datasetId)}/profile`}>数据画像</Link>
        </Button>
      }
    >
      <EvidenceSuiteWorkbenchShell {...state} />
    </OperationalWorkspace>
  )
}
