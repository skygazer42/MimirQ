/**
 * Workbench - 主工作台（包含 TopBar、Sidebar 和 Preview）
 */
'use client'

import { Layers } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { TopBar } from './top-bar'
import { Sidebar } from './sidebar'
import { OriginalPreview } from './preview/original-preview'
import { ChunkList } from './preview/chunk-list'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { PipelineRail, WorkbenchPane, WorkbenchPanelDialog, WorkbenchScaffold } from '@/components/workbench'

export function Workbench() {
  const t = useTranslations('ChunkPreview')
  const { currentFile, currentFileItem, showOriginalPanel, showSettingsPanel, toggleSettingsPanel } = useChunkPreview()
  const toolbar = currentFile && currentFileItem ? <TopBar /> : null

  return (
    <>
      <WorkbenchScaffold
        title={t('workbench.title')}
        description={t('workbench.description')}
        icon={Layers}
        iconColor="text-primary"
        size="full"
        pipelineRail={<PipelineRail />}
        toolbar={toolbar}
        leftPanel={
          <WorkbenchPane bodyClassName="p-0">
            <Sidebar variant="pane" />
          </WorkbenchPane>
        }
        mainPanel={
          <WorkbenchPane className="flex-1 min-w-0" bodyClassName="p-0 overflow-hidden">
            <main className="flex h-full min-h-0 min-w-0 flex-col lg:flex-row overflow-hidden bg-background">
              {showOriginalPanel ? <OriginalPreview /> : null}
              <ChunkList />
            </main>
          </WorkbenchPane>
        }
      />

      {/* Mobile: settings panel as a modal (sheet-like) */}
      <WorkbenchPanelDialog
        open={showSettingsPanel}
        onOpenChange={(open) => {
          if (open !== showSettingsPanel) toggleSettingsPanel()
        }}
        title={t('workbench.settingsPanelTitle')}
      >
        <Sidebar variant="dialog" />
      </WorkbenchPanelDialog>
    </>
  )
}
