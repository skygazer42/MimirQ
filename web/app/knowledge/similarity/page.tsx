'use client'

import dynamic from 'next/dynamic'

import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'

const RagvizSimilarityWorkbench = dynamic(() => import('@/components/ragviz/similarity-workbench').then((mod) => mod.RagvizSimilarityWorkbench), {
  ssr: false,
  loading: () => <PageLoading message="正在加载 Similarity Workbench..." srMessage="Loading similarity workbench" />,
})

export default function KnowledgeSimilarityPage() {
  return (
    <AppFrame mainClassName="overflow-hidden">
      <RagvizSimilarityWorkbench />
    </AppFrame>
  )
}
