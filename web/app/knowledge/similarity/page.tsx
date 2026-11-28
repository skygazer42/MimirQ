'use client'

import dynamic from 'next/dynamic'

import { AppFrame } from '@/components/app-frame'
import { PageLoading } from '@/components/ui/page-loading'

const RagvizSimilarityWorkbench = dynamic(
  () => import('@/components/ragviz/similarity-workbench').then((mod) => mod.RagvizSimilarityWorkbench),
  {
    ssr: false,
    loading: () => <PageLoading message="正在加载向量相似度诊断…" srMessage="正在加载向量相似度诊断" />,
  },
)

export default function KnowledgeSimilarityPage() {
  return (
    <AppFrame mainClassName="overflow-hidden">
      <RagvizSimilarityWorkbench />
    </AppFrame>
  )
}
