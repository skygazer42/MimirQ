'use client'

import { Copy, Hash } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { useState } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { IconButton } from '@/components/ui/icon-button'
import { cn, formatDate } from '@/lib/utils'
import type { DocumentVersionList } from '@/types/documents'

type DocumentVersionsDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  versions: DocumentVersionList | null
  isLoading: boolean
  error: string | null
  disabled: boolean
  onRefresh: () => void
  onCopy: (text: string) => void
  onActivate: (pipelineHash: string) => Promise<void>
  onDelete: (pipelineHash: string) => Promise<void>
}

type VersionConfirmation = {
  action: 'activate' | 'delete'
  pipelineHash: string
  versions: DocumentVersionList
}

export function DocumentVersionsDialog({ open, onOpenChange, ...contentProps }: Readonly<DocumentVersionsDialogProps>) {
  const t = useTranslations('DocumentVersionsDialog')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" className="w-full gap-2 sm:w-auto">
          <Hash className="size-4" aria-hidden="true" />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      {open && <DocumentVersionsContent {...contentProps} />}
    </Dialog>
  )
}

function DocumentVersionsContent({
  versions,
  isLoading,
  error,
  disabled,
  onRefresh,
  onCopy,
  onActivate,
  onDelete,
}: Readonly<Omit<DocumentVersionsDialogProps, 'open' | 'onOpenChange'>>) {
  const t = useTranslations('DocumentVersionsDialog')
  const [confirmation, setConfirmation] = useState<VersionConfirmation | null>(null)
  const displayedVersions = confirmation === null ? versions : confirmation.versions
  const versionItems = displayedVersions?.items
  const activePipelineHash = displayedVersions?.active_pipeline_hash
  const hasActivePipeline = activePipelineHash !== null && activePipelineHash !== undefined

  return (
    <DialogContent className="max-h-[90dvh] max-w-2xl overflow-y-auto">
      <DialogTitle>{t('title')}</DialogTitle>
      <DialogDescription className="text-xs">{t('description')}</DialogDescription>

      <div className="mt-4 space-y-3">
        {isLoading ? (
          <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
            <Hash className="size-4" aria-hidden="true" />
            {t('loading')}
          </div>
        ) : null}

        {error !== null ? (
          <Alert variant="destructive">
            <AlertTitle>{t('errors.load')}</AlertTitle>
            <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
              <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{error}</span>
              <Button type="button" variant="outline" size="sm" onClick={onRefresh} disabled={isLoading}>
                {t('actions.retry')}
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        {displayedVersions !== null && (
          <div className="rounded-xl border border-border/60 bg-muted/20 p-3">
            <div className="text-xs text-muted-foreground">{t('currentHash.label')}</div>
            <div className="mt-2 flex items-center justify-between gap-2">
              <div className="min-w-0 break-all font-mono text-xs text-foreground">
                {hasActivePipeline ? activePipelineHash : t('currentHash.empty')}
              </div>
              {hasActivePipeline ? (
                <IconButton
                  label={t('actions.copyActiveHash')}
                  variant="ghost"
                  className="h-9 w-9 text-muted-foreground hover:text-foreground"
                  onClick={() => onCopy(activePipelineHash)}
                >
                  <Copy className="h-4 w-4" />
                </IconButton>
              ) : null}
            </div>
          </div>
        )}

        {displayedVersions !== null && versionItems !== undefined && versionItems.length > 0 ? (
          <div className="space-y-2">
            {versionItems.map((version) => (
              <div
                key={version.pipeline_hash}
                className={cn(
                  'flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-card p-3',
                  version.active && 'border-primary/30 bg-primary/5',
                )}
              >
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="break-all font-mono text-xs text-foreground">{version.pipeline_hash}</span>
                    {version.active ? (
                      <span className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                        {t('activeBadge')}
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {t('meta.chunkCount', { count: version.chunk_count })}
                    {version.last_chunk_at === null || version.last_chunk_at === undefined ? null : (
                      <> · {t('meta.updatedAt', { date: formatDate(version.last_chunk_at) })}</>
                    )}
                  </div>
                </div>

                <div className="flex flex-shrink-0 items-center gap-2">
                  <IconButton
                    label={t('actions.copyVersionHash')}
                    variant="ghost"
                    className="h-9 w-9 text-muted-foreground hover:text-foreground"
                    onClick={() => onCopy(version.pipeline_hash)}
                  >
                    <Copy className="h-4 w-4" />
                  </IconButton>

                  {!version.active &&
                    (['activate', 'delete'] as const).map((action) => {
                      const isDelete = action === 'delete'
                      return (
                        <ConfirmDialog
                          key={action}
                          open={confirmation?.action === action && confirmation.pipelineHash === version.pipeline_hash}
                          onOpenChange={(open) =>
                            setConfirmation(
                              open
                                ? { action, pipelineHash: version.pipeline_hash, versions: displayedVersions }
                                : null,
                            )
                          }
                          title={t(`dialogs.${action}.title`)}
                          description={t(`dialogs.${action}.description`, {
                            hash: `${version.pipeline_hash.slice(0, 12)}…`,
                          })}
                          confirmLabel={t(`dialogs.${action}.confirm`)}
                          cancelLabel={t(`dialogs.${action}.cancel`)}
                          confirmVariant={isDelete ? 'destructive' : 'default'}
                          confirmDisabled={disabled}
                          onConfirm={() => (isDelete ? onDelete : onActivate)(version.pipeline_hash)}
                        >
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={disabled}
                            className={
                              isDelete ? 'text-destructive hover:bg-destructive/10 hover:text-destructive' : undefined
                            }
                          >
                            {t(`actions.${action}`)}
                          </Button>
                        </ConfirmDialog>
                      )
                    })}
                </div>
              </div>
            ))}
          </div>
        ) : displayedVersions !== null && !isLoading && error === null ? (
          <EmptyState
            icon={Hash}
            title={t('empty.title')}
            description={t('empty.description')}
            className="min-h-[240px]"
          />
        ) : null}

        <div className="text-xs text-muted-foreground">{t('hint')}</div>
      </div>
    </DialogContent>
  )
}
