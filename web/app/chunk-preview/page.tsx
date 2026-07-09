'use client'

import dynamic from 'next/dynamic'
import { AppFrame } from '@/components/app-frame'
import { KNOWLEDGE_OPS_BACKGROUND_CLASS } from '@/components/ui/knowledge-ops-hero'
import { PageLoading } from '@/components/ui/page-loading'

const ChunkPreview = dynamic(
  () => import('@/components/chunk-preview').then((mod) => mod.ChunkPreview),
  {
    ssr: false,
    loading: () => <PageLoading message="正在加载预览组件..." srMessage="Loading chunk preview component" />,
  }
)

export default function ChunkPreviewPage() {
  return (
    <AppFrame>
      <div className={KNOWLEDGE_OPS_BACKGROUND_CLASS}>
        <ChunkPreview />
      </div>
    </AppFrame>
  )
}
