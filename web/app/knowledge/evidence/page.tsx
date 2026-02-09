'use client'

import { Search } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { EvidenceWorkbench } from '@/components/ragviz/evidence-workbench'
import { PageScaffold } from '@/components/ui/page-scaffold'

export default function KnowledgeEvidencePage() {
  return (
    <AppFrame>
      <PageScaffold
        title="Evidence Workbench"
        description="检索-only Evidence API 调试台：查看 citations / has_evidence / abstain 信号（不生成回答）"
        icon={Search}
        iconColor="text-sky-600 dark:text-sky-400"
      >
        <EvidenceWorkbench />
      </PageScaffold>
    </AppFrame>
  )
}

