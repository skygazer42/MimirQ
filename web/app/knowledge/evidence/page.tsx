'use client'

import dynamic from 'next/dynamic'
import { Search } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { EvidenceOpsPanel } from '@/components/evidence/evidence-ops-panel'

const EvidenceWorkbench = dynamic(() => import('@/components/ragviz/evidence-workbench').then((mod) => mod.EvidenceWorkbench), {
  ssr: false,
  loading: () => <PageLoading message="正在加载 Evidence Workbench..." srMessage="Loading evidence workbench" />,
})

export default function KnowledgeEvidencePage() {
  return (
    <AppFrame>
      <PageScaffold
        title="Evidence Workbench"
        description="检索-only Evidence API 调试台：查看 citations / has_evidence / abstain 信号（不生成回答）"
        icon={Search}
        iconColor="text-info dark:text-sky-400"
      >
        <EvidenceWorkbench />
        <EvidenceOpsPanel />
      </PageScaffold>
    </AppFrame>
  )
}
