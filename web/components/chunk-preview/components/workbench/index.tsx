/**
 * Workbench - 主工作台（包含 TopBar、Sidebar 和 Preview）
 */
'use client'

import { TopBar } from './top-bar'
import { Sidebar } from './sidebar'
import { OriginalPreview } from './preview/original-preview'
import { ChunkList } from './preview/chunk-list'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { Dialog, DialogContent } from '@/components/ui/dialog'

export function Workbench() {
  const { showOriginalPanel, showSettingsPanel, toggleSettingsPanel } = useChunkPreview()

  return (
    <div className="flex flex-col h-full bg-background text-foreground font-sans overflow-hidden">
      {/* 顶部栏 */}
      <TopBar />

      <div className="flex flex-1 overflow-hidden">
        {/* 左侧配置栏 */}
        <div className="hidden lg:flex">
          <Sidebar />
        </div>

        {/* 主区域：原文 vs 预览 */}
        <main className="flex-1 flex flex-col lg:flex-row overflow-hidden bg-background">
          {/* 左侧原文 */}
          {showOriginalPanel ? <OriginalPreview /> : null}

          {/* 右侧切片 */}
          <ChunkList />
        </main>
      </div>

      {/* Mobile: settings panel as a modal (sheet-like) */}
      <Dialog
        open={showSettingsPanel}
        onOpenChange={(open) => {
          if (open !== showSettingsPanel) toggleSettingsPanel()
        }}
      >
        <DialogContent className="w-[92vw] max-w-[92vw] h-[85vh] max-h-[85vh] p-0 overflow-hidden">
          <Sidebar variant="dialog" />
        </DialogContent>
      </Dialog>
    </div>
  )
}
