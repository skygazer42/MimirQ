'use client'

import type { ConnectorRunOut, Dataset } from '@/types'
import type { ChangeEvent, Ref } from 'react'
import { useCallback, useImperativeHandle, useRef, useState } from 'react'
import { ChevronDown, Plus } from '@/components/icons'
import { useTranslations } from 'next-intl'

import { KnowledgeImportMenu } from '@/components/knowledge/import/knowledge-import-menu'
import { KnowledgeJiraProjectDialog } from '@/components/knowledge/import/knowledge-jira-project-dialog'
import { KnowledgePipelineConfigDialog } from '@/components/knowledge/import/knowledge-pipeline-config-dialog'
import { KnowledgeUrlBatchDialog } from '@/components/knowledge/import/knowledge-url-batch-dialog'
import { KnowledgeUrlImportDialog } from '@/components/knowledge/import/knowledge-url-import-dialog'
import { KnowledgeWebCrawlDialog } from '@/components/knowledge/import/knowledge-web-crawl-dialog'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'
import { cn } from '@/lib/utils'

export type KnowledgeImportSource = 'files' | 'url' | 'crawl'
export type KnowledgeWorkbenchActionsHandle = {
  openImport: (source: KnowledgeImportSource) => void
}

type KnowledgeWorkbenchActionsProps = {
  actionsRef?: Ref<KnowledgeWorkbenchActionsHandle>
  datasets: Dataset[]
  datasetsLoading: boolean
  selectedDatasetId?: string
  datasetDefaultValue: string
  handleFileUpload: (event: ChangeEvent<HTMLInputElement>) => void
  uploadDocumentFromUrl: (params: { url: string; filename?: string; dataset_id?: string }) => Promise<unknown>
  loadDocuments: () => void | Promise<void>
  loadConnectorRuns: (params?: { datasetId?: string }) => void | Promise<void>
  onConnectorRunCreated?: (run: ConnectorRunOut) => void
  open?: boolean
  onOpenChange?: (open: boolean) => void
  className?: string
}

export function KnowledgeWorkbenchActions({
  actionsRef,
  datasets,
  datasetsLoading,
  selectedDatasetId,
  datasetDefaultValue,
  handleFileUpload,
  uploadDocumentFromUrl,
  loadDocuments,
  loadConnectorRuns,
  onConnectorRunCreated,
  open,
  onOpenChange,
  className,
}: Readonly<KnowledgeWorkbenchActionsProps>) {
  const t = useTranslations('KnowledgeWorkbenchActions')
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)
  const [pipelineConfigOpen, setPipelineConfigOpen] = useState(false)
  const [urlImportOpen, setUrlImportOpen] = useState(false)
  const [urlBatchOpen, setUrlBatchOpen] = useState(false)
  const [webCrawlOpen, setWebCrawlOpen] = useState(false)
  const [jiraProjectOpen, setJiraProjectOpen] = useState(false)

  const handleOpenFilePicker = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  useImperativeHandle(actionsRef, () => ({
    openImport: source => {
      if (source === 'files') handleOpenFilePicker()
      else {
        returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
        if (source === 'url') setUrlImportOpen(true)
        else setWebCrawlOpen(true)
      }
    },
  }), [handleOpenFilePicker])

  const restoreImportFocus = (event: Event) => {
    const element = returnFocusRef.current
    returnFocusRef.current = null
    if (element?.isConnected) {
      event.preventDefault()
      element.focus()
    }
  }

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={UPLOAD_ACCEPT}
        className="hidden"
        onChange={handleFileUpload}
      />

      <DropdownMenu open={open} onOpenChange={onOpenChange}>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            size="sm"
            className={cn(
              'gap-2 shadow-none',
              className,
            )}
          >
            <Plus className="size-4" />
            <span>{t('importOrCreate')}</span>
            <ChevronDown className="size-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-72">
          <KnowledgeImportMenu
            onUploadFiles={handleOpenFilePicker}
            onOpenUrlImport={() => setUrlImportOpen(true)}
            onOpenUrlBatch={() => setUrlBatchOpen(true)}
            onOpenWebCrawl={() => setWebCrawlOpen(true)}
            onOpenJiraProject={() => setJiraProjectOpen(true)}
            onOpenPipelineConfig={() => setPipelineConfigOpen(true)}
          />
        </DropdownMenuContent>
      </DropdownMenu>

      <KnowledgePipelineConfigDialog open={pipelineConfigOpen} onOpenChange={setPipelineConfigOpen} />

      <KnowledgeUrlImportDialog
        open={urlImportOpen}
        onOpenChange={setUrlImportOpen}
        onCloseAutoFocus={restoreImportFocus}
        datasets={datasets}
        datasetsLoading={datasetsLoading}
        selectedDatasetId={selectedDatasetId}
        datasetDefaultValue={datasetDefaultValue}
        uploadDocumentFromUrl={uploadDocumentFromUrl}
        onAfterImport={loadDocuments}
      />

      <KnowledgeUrlBatchDialog
        open={urlBatchOpen}
        onOpenChange={setUrlBatchOpen}
        datasets={datasets}
        datasetsLoading={datasetsLoading}
        selectedDatasetId={selectedDatasetId}
        datasetDefaultValue={datasetDefaultValue}
        loadDocuments={loadDocuments}
        loadConnectorRuns={loadConnectorRuns}
        onRunCreated={onConnectorRunCreated}
      />

      <KnowledgeWebCrawlDialog
        open={webCrawlOpen}
        onOpenChange={setWebCrawlOpen}
        onCloseAutoFocus={restoreImportFocus}
        datasets={datasets}
        datasetsLoading={datasetsLoading}
        selectedDatasetId={selectedDatasetId}
        datasetDefaultValue={datasetDefaultValue}
        loadDocuments={loadDocuments}
        loadConnectorRuns={loadConnectorRuns}
        onRunCreated={onConnectorRunCreated}
      />

      <KnowledgeJiraProjectDialog
        open={jiraProjectOpen}
        onOpenChange={setJiraProjectOpen}
        datasets={datasets}
        datasetsLoading={datasetsLoading}
        selectedDatasetId={selectedDatasetId}
        datasetDefaultValue={datasetDefaultValue}
        loadDocuments={loadDocuments}
        loadConnectorRuns={loadConnectorRuns}
        onRunCreated={onConnectorRunCreated}
      />
    </>
  )
}
