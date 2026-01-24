/**
 * Workbench - 主工作台（包含 TopBar、Sidebar 和 Preview）
 */
'use client'

import { TopBar } from './top-bar'
import { Sidebar } from './sidebar'
import { OriginalPreview } from './preview/original-preview'
import { ChunkList } from './preview/chunk-list'
import { useChunkPreview } from '@/components/chunk-preview/context'

export function Workbench() {
  const { showOriginalPanel } = useChunkPreview()

  return (
    <div className="flex flex-col h-full bg-background/60 text-foreground font-sans overflow-hidden">
      {/* 顶部栏 */}
      <TopBar />

      <div className="flex flex-1 overflow-hidden">
        {/* 左侧配置栏 */}
        <Sidebar />

        {/* 主区域：原文 vs 预览 */}
        <main className="flex-1 flex flex-col lg:flex-row overflow-hidden bg-background/60">
          {/* 左侧原文 */}
          {showOriginalPanel ? <OriginalPreview /> : null}

          {/* 右侧切片 */}
          <ChunkList />
        </main>
      </div>
    </div>
  )
}
