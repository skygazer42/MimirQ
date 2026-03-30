'use client'

import { EvidenceSuiteWorkbenchShell } from '@/components/evidence/evidence-suite-workbench-shell'
import { useEvidenceSuiteWorkbenchState } from '@/components/evidence/use-evidence-suite-workbench-state'

export function EvidenceSuiteWorkbench({
  datasetId,
  initialFeedbackId,
}: Readonly<{
  datasetId: string
  initialFeedbackId?: string
}>) {
  const state = useEvidenceSuiteWorkbenchState(datasetId, { initialFeedbackId })
  return <EvidenceSuiteWorkbenchShell {...state} />
}
