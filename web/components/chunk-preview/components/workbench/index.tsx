/**
 * Workbench - 主工作台（包含 TopBar、Sidebar 和 Preview）
 */
'use client'

import { TopBar } from './top-bar'
import { Sidebar } from './sidebar'
import { OriginalPreview } from './preview/original-preview'
import { ChunkList } from './preview/chunk-list'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { PipelineRail, WorkbenchPane, WorkbenchPanelDialog } from '@/components/workbench'

export function Workbench() {
  const { showOriginalPanel, showSettingsPanel, toggleSettingsPanel } = useChunkPreview()

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background text-foreground font-sans">
      {/* 顶部栏 */}
      <TopBar />

      <div className="px-4 py-3 border-b border-border/60 bg-background/70 flex-shrink-0">
        <PipelineRail />
      </div>

      <div className="flex flex-1 min-h-0 overflow-hidden gap-4 p-4">
        {/* Left: settings */}
        <div className="hidden lg:flex min-h-0">
          <WorkbenchPane className="w-80" bodyClassName="p-0">
            <Sidebar variant="pane" />
          </WorkbenchPane>
        </div>

        {/* Main: original vs chunks */}
        <WorkbenchPane className="flex-1 min-w-0" bodyClassName="p-0 overflow-hidden">
          <main className="flex h-full min-h-0 min-w-0 flex-col lg:flex-row overflow-hidden bg-background">
            {showOriginalPanel ? <OriginalPreview /> : null}
            <ChunkList />
          </main>
        </WorkbenchPane>
      </div>

      {/* Mobile: settings panel as a modal (sheet-like) */}
      <WorkbenchPanelDialog
        open={showSettingsPanel}
        onOpenChange={(open) => {
          if (open !== showSettingsPanel) toggleSettingsPanel()
        }}
        title="参数面板"
      >
        <Sidebar variant="dialog" />
      </WorkbenchPanelDialog>
    </div>
  )
}
