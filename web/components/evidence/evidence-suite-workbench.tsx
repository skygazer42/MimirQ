'use client'

import { EvidenceSuiteWorkbenchShell } from '@/components/evidence/evidence-suite-workbench-shell'
import { useEvidenceSuiteWorkbenchState } from '@/components/evidence/use-evidence-suite-workbench-state'

export function EvidenceSuiteWorkbench({ datasetId }: Readonly<{ datasetId: string }>) {
  const state = useEvidenceSuiteWorkbenchState(datasetId)
  return <EvidenceSuiteWorkbenchShell {...state} />
}
