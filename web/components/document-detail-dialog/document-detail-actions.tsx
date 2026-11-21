'use client'

import { useTranslations } from 'next-intl'

import { Download } from '@/components/icons'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { LoadingButton } from '@/components/ui/loading-button'

export type DocumentGraphAction = 'extract' | 'delete'

type DocumentDetailActionsProps = Readonly<{
  graphAction: DocumentGraphAction | undefined
  downloadPending: boolean
  canExtract: boolean
  onExtractGraph: () => void
  onDeleteGraph: () => Promise<void>
  onDownloadCleanDocx: () => void
}>

export function DocumentDetailActions({
  graphAction,
  downloadPending,
  canExtract,
  onExtractGraph,
  onDeleteGraph,
  onDownloadCleanDocx,
}: DocumentDetailActionsProps) {
  const t = useTranslations('DocumentDetailDialog')
  const graphBusy = graphAction !== undefined

  return (
    <>
      <LoadingButton
        type="button"
        variant="outline"
        loading={graphAction === 'extract'}
        disabled={graphBusy || !canExtract}
        onClick={onExtractGraph}
      >
        {t('kg.extract')}
      </LoadingButton>
      <LoadingButton
        type="button"
        variant="outline"
        loading={downloadPending}
        onClick={onDownloadCleanDocx}
        className="gap-2"
      >
        <Download className="h-4 w-4" aria-hidden="true" />
        {t('actions.downloadCleanDocx')}
      </LoadingButton>
      <ConfirmDialog
        title={t('kg.deleteDialog.title')}
        description={t('kg.deleteDialog.description')}
        confirmLabel={t('kg.deleteDialog.confirm')}
        cancelLabel={t('kg.deleteDialog.cancel')}
        confirmVariant="destructive"
        confirmDisabled={graphBusy}
        onConfirm={onDeleteGraph}
      >
        <LoadingButton
          type="button"
          variant="outline"
          loading={graphAction === 'delete'}
          disabled={graphBusy}
          className="text-destructive hover:bg-destructive/10 hover:text-destructive"
        >
          {t('kg.delete')}
        </LoadingButton>
      </ConfirmDialog>
    </>
  )
}
