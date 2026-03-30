'use client'

import { Copy, Hash } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { IconButton } from '@/components/ui/icon-button'
import { cn, formatDate } from '@/lib/utils'
import type { DocumentVersionList } from '@/types'

interface DocumentVersionsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  activePipelineHash: string | null | undefined
  versions: DocumentVersionList | null
  isLoading: boolean
  error: string | null
  isWorking: boolean
  onRefresh: () => void
  onCopy: (text: string) => void
  onActivate: (pipelineHash: string) => void
  onDelete: (pipelineHash: string) => void
}

export function DocumentVersionsDialog({
  open,
  onOpenChange,
  activePipelineHash,
  versions,
  isLoading,
  error,
  isWorking,
  onRefresh,
  onCopy,
  onActivate,
  onDelete,
}: Readonly<DocumentVersionsDialogProps>) {
  const t = useTranslations('DocumentVersionsDialog')
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" className="w-full gap-2 sm:w-auto">
          <Hash className="h-4 w-4" />
          {t("trigger")}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogTitle>{t('title')}</DialogTitle>
        <DialogDescription className="text-xs">
          {t('description')}
        </DialogDescription>

        <div className="mt-4 space-y-3">
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Hash className="h-4 w-4" />
              {t('loading')}
            </div>
          ) : null}

          {error ? (
            <Alert variant="destructive">
              <AlertTitle>{t('errors.load')}</AlertTitle>
              <AlertDescription className="flex items-center justify-between gap-3">
                <span className="min-w-0 flex-1">{error}</span>
                <Button variant="outline" size="sm" onClick={onRefresh}>
                  {t('actions.retry')}
                </Button>
              </AlertDescription>
            </Alert>
          ) : null}

          <div className="rounded-xl border border-border/60 bg-muted/20 p-3">
            <div className="text-xs text-muted-foreground">{t('currentHash.label')}</div>
            <div className="mt-2 flex items-center justify-between gap-2">
              <div className="min-w-0 font-mono text-xs text-foreground">{activePipelineHash || '-'}</div>
              <IconButton
                label={t('actions.copyActiveHash')}
                variant="ghost"
                className="h-9 w-9 text-muted-foreground hover:text-foreground"
                disabled={!activePipelineHash}
                onClick={() => onCopy(String(activePipelineHash || ''))}
              >
                <Copy className="h-4 w-4" />
              </IconButton>
            </div>
          </div>

          {!isLoading && !error ? (
            versions?.items?.length ? (
              <div className="space-y-2">
                {versions.items.map((version) => (
                  <div
                    key={version.pipeline_hash}
                    className={cn(
                      'flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-card p-3',
                      version.active ? 'border-primary/30 bg-primary/5' : 'bg-card'
                    )}
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs text-foreground">{version.pipeline_hash}</span>
                        {version.active ? (
                          <span className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                            {t('activeBadge')}
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {t('meta.chunkCount', { count: version.chunk_count })}
                        {version.last_chunk_at ? ` · ${t('meta.updatedAt', { date: formatDate(version.last_chunk_at) })}` : ''}
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

                      {version.active ? (
                        <Button size="sm" variant="secondary" disabled>
                          {t('actions.active')}
                        </Button>
                      ) : (
                        <>
                          <ConfirmDialog
                            title={t("dialogs.activate.title")}
                            description={t('dialogs.activate.description', { hash: `${version.pipeline_hash.slice(0, 12)}…` })}
                            confirmLabel={t('dialogs.activate.confirm')}
                            cancelLabel={t('dialogs.activate.cancel')}
                            confirmVariant="default"
                            confirmDisabled={isWorking}
                            onConfirm={() => onActivate(version.pipeline_hash)}
                          >
                            <Button size="sm" variant="outline" disabled={isWorking}>
                              {t('actions.activate')}
                            </Button>
                          </ConfirmDialog>
                          <ConfirmDialog
                            title={t('dialogs.delete.title')}
                            description={t('dialogs.delete.description', { hash: `${version.pipeline_hash.slice(0, 12)}…` })}
                            confirmLabel={t('dialogs.delete.confirm')}
                            cancelLabel={t('dialogs.delete.cancel')}
                            confirmVariant="destructive"
                            confirmDisabled={isWorking}
                            onConfirm={() => onDelete(version.pipeline_hash)}
                          >
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={isWorking}
                              className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                            >
                              {t('actions.delete')}
                            </Button>
                          </ConfirmDialog>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={Hash}
                title={t("empty.title")}
                description={t('empty.description')}
                className="min-h-[240px]"
              />
            )
          ) : null}

          <div className="text-xs text-muted-foreground">
            {t('hint')}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
