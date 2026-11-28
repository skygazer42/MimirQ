'use client'

import dynamic from 'next/dynamic'

import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'
import { EvidenceOpsPanel } from '@/components/evidence/evidence-ops-panel'

const EvidenceWorkbench = dynamic(
  () => import('@/components/ragviz/evidence-workbench').then((mod) => mod.EvidenceWorkbench),
  {
    ssr: false,
    loading: () => <PageLoading message="正在加载证据调试…" srMessage="正在加载证据调试" />,
  },
)

export default function KnowledgeEvidencePage() {
  return (
    <AppFrame showBackground={false}>
      <EvidenceWorkbench tools={<EvidenceOpsPanel />} />
    </AppFrame>
  )
}
