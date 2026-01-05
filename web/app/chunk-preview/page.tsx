'use client'

import { Navbar } from '@/components/navbar'
import { ChunkPreview } from '@/components/chunk-preview'

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
