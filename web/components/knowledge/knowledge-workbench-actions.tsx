'use client'

import type { ConnectorRunOut, Dataset } from '@/types'
import type { ChangeEvent } from 'react'
import { useCallback, useRef, useState } from 'react'
import { Plus } from 'lucide-react'
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

type KnowledgeWorkbenchActionsProps = {
  datasets: Dataset[]
  datasetsLoading: boolean
  selectedDatasetId?: string
  datasetDefaultValue: string
  handleFileUpload: (event: ChangeEvent<HTMLInputElement>) => void
  uploadDocumentFromUrl: (params: { url: string; filename?: string; dataset_id?: string }) => Promise<unknown>
  loadDocuments: () => void | Promise<void>
  loadConnectorRuns: (params?: { datasetId?: string }) => void | Promise<void>
  onConnectorRunCreated?: (run: ConnectorRunOut) => void
  className?: string
}

export function KnowledgeWorkbenchActions({
  datasets,
  datasetsLoading,
  selectedDatasetId,
  datasetDefaultValue,
  handleFileUpload,
  uploadDocumentFromUrl,
  loadDocuments,
  loadConnectorRuns,
  onConnectorRunCreated,
  className,
}: Readonly<KnowledgeWorkbenchActionsProps>) {
  const t = useTranslations('KnowledgeWorkbenchActions')
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [pipelineConfigOpen, setPipelineConfigOpen] = useState(false)
  const [urlImportOpen, setUrlImportOpen] = useState(false)
  const [urlBatchOpen, setUrlBatchOpen] = useState(false)
  const [webCrawlOpen, setWebCrawlOpen] = useState(false)
  const [jiraProjectOpen, setJiraProjectOpen] = useState(false)

  const handleOpenFilePicker = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

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

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" size="sm" className={className}>
            <Plus className="size-4" />
            {t('importOrCreate')}
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
