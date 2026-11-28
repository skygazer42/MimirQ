'use client'

import { useCallback, useImperativeHandle, useRef, useState, type ChangeEvent, type Ref } from 'react'
import { ChevronDown, Plus } from '@/components/icons'
import { useTranslations } from 'next-intl'

import { KnowledgeImportMenu } from '@/components/knowledge/import/knowledge-import-menu'
import { KnowledgeJiraProjectDialog } from '@/components/knowledge/import/knowledge-jira-project-dialog'
import { KnowledgePipelineConfigDialog } from '@/components/knowledge/import/knowledge-pipeline-config-dialog'
import { KnowledgeUrlBatchDialog } from '@/components/knowledge/import/knowledge-url-batch-dialog'
import { KnowledgeUrlImportDialog } from '@/components/knowledge/import/knowledge-url-import-dialog'
import { KnowledgeWebCrawlDialog } from '@/components/knowledge/import/knowledge-web-crawl-dialog'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import type { LoadConnectorRuns } from '@/hooks/use-connector-runs'
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'
import { cn } from '@/lib/utils'
import type { ConnectorRunOut } from '@/types/connectors'
import type { Dataset } from '@/types/datasets'

export type KnowledgeImportSource = 'files' | 'url' | 'crawl'
export type KnowledgeWorkbenchActionsHandle = {
  openImport: (source: KnowledgeImportSource) => void
}

type WorkbenchDialog = Exclude<KnowledgeImportSource, 'files'> | 'url-batch' | 'jira' | 'pipeline-config'

type KnowledgeWorkbenchActionsProps = {
  actionsRef?: Ref<KnowledgeWorkbenchActionsHandle>
  datasets: Dataset[]
  datasetsLoading: boolean
  selectedDatasetId?: string
  datasetDefaultValue: string
  handleFileUpload: (event: ChangeEvent<HTMLInputElement>) => void
  uploadDocumentFromUrl: (params: { url: string; filename?: string; dataset_id?: string }) => Promise<unknown>
  loadDocuments: () => void | Promise<void>
  loadConnectorRuns: LoadConnectorRuns
  onConnectorRunCreated?: (run: ConnectorRunOut) => void
  open?: boolean
  onOpenChange?: (open: boolean) => void
  hideTrigger?: boolean
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
  hideTrigger = false,
  className,
}: Readonly<KnowledgeWorkbenchActionsProps>) {
  const t = useTranslations('KnowledgeWorkbenchActions')
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const importTriggerRef = useRef<HTMLButtonElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)
  const [openDialog, setOpenDialog] = useState<WorkbenchDialog | null>(null)

  const handleOpenFilePicker = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  useImperativeHandle(
    actionsRef,
    () => ({
      openImport: (source) => {
        if (source === 'files') {
          handleOpenFilePicker()
          return
        }
        returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
        setOpenDialog(source)
      },
    }),
    [handleOpenFilePicker],
  )

  function handleDialogOpenChange(dialog: WorkbenchDialog, isOpen: boolean) {
    if (isOpen) {
      setOpenDialog(dialog)
      return
    }
    setOpenDialog((currentDialog) => (currentDialog === dialog ? null : currentDialog))
  }

  function openImportFromMenu(dialog: 'url' | 'crawl') {
    returnFocusRef.current = importTriggerRef.current
    setOpenDialog(dialog)
  }

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

      {!hideTrigger ? (
        <DropdownMenu open={open} onOpenChange={onOpenChange}>
          <DropdownMenuTrigger asChild>
            <Button ref={importTriggerRef} type="button" size="sm" className={cn('gap-2 shadow-none', className)}>
              <Plus className="size-4" />
              <span>{t('importOrCreate')}</span>
              <ChevronDown className="size-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-72">
            <KnowledgeImportMenu
              onUploadFiles={handleOpenFilePicker}
              onOpenUrlImport={() => openImportFromMenu('url')}
              onOpenUrlBatch={() => setOpenDialog('url-batch')}
              onOpenWebCrawl={() => openImportFromMenu('crawl')}
              onOpenJiraProject={() => setOpenDialog('jira')}
              onOpenPipelineConfig={() => setOpenDialog('pipeline-config')}
            />
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}

      <KnowledgePipelineConfigDialog
        open={openDialog === 'pipeline-config'}
        onOpenChange={(isOpen) => handleDialogOpenChange('pipeline-config', isOpen)}
      />

      <KnowledgeUrlImportDialog
        open={openDialog === 'url'}
        onOpenChange={(isOpen) => handleDialogOpenChange('url', isOpen)}
        onCloseAutoFocus={restoreImportFocus}
        datasets={datasets}
        datasetsLoading={datasetsLoading}
        selectedDatasetId={selectedDatasetId}
        datasetDefaultValue={datasetDefaultValue}
        uploadDocumentFromUrl={uploadDocumentFromUrl}
        onAfterImport={loadDocuments}
      />

      <KnowledgeUrlBatchDialog
        open={openDialog === 'url-batch'}
        onOpenChange={(isOpen) => handleDialogOpenChange('url-batch', isOpen)}
        datasets={datasets}
        datasetsLoading={datasetsLoading}
        selectedDatasetId={selectedDatasetId}
        datasetDefaultValue={datasetDefaultValue}
        loadDocuments={loadDocuments}
        loadConnectorRuns={loadConnectorRuns}
        onRunCreated={onConnectorRunCreated}
      />

      <KnowledgeWebCrawlDialog
        open={openDialog === 'crawl'}
        onOpenChange={(isOpen) => handleDialogOpenChange('crawl', isOpen)}
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
        open={openDialog === 'jira'}
        onOpenChange={(isOpen) => handleDialogOpenChange('jira', isOpen)}
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
