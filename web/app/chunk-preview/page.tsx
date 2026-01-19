'use client'

import dynamic from 'next/dynamic'
import { Navbar } from '@/components/navbar'
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
    <div className="flex h-screen overflow-hidden bg-background">
      <Navbar />

      <main className="flex-1 flex flex-col overflow-hidden min-h-0">
        <ChunkPreview />
      </main>
    </div>
  )
}
