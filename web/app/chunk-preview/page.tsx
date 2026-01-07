'use client'

import dynamic from 'next/dynamic'
import { Navbar } from '@/components/navbar'

const ChunkPreview = dynamic(
  () => import('@/components/chunk-preview').then((mod) => mod.ChunkPreview),
  {
    ssr: false,
    loading: () => (
      <div
        role="status"
        aria-live="polite"
        className="flex-1 flex items-center justify-center bg-gray-50"
      >
        <div className="flex items-center gap-3 text-slate-500 font-medium">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-200 border-t-blue-600" />
          <span>正在加载预览组件...</span>
          <span className="sr-only">Loading chunk preview component</span>
        </div>
      </div>
    ),
  }
)

export default function ChunkPreviewPage() {
  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Navbar />

      <main className="flex-1 flex flex-col overflow-hidden min-h-0">
        <ChunkPreview />
      </main>
    </div>
  )
}
