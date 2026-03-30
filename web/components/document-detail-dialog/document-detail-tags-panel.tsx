'use client'

import type { ComponentProps, ReactNode } from 'react'

import { Pencil, Tags } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { TagInput } from '@/components/ui/tag-input'
import { DocumentTags } from '@/components/documents/document-tags'

type DocumentDetailTagsPanelProps = Readonly<{
  editing: boolean
  saveAction: ComponentProps<'form'>['action']
  saveButton: ReactNode
  isSaving: boolean
  tagsDraft: string[]
  onTagsDraftChange: (next: string[]) => void
  optimisticTags: string[]
  tagsError: string | null
  onBeginEdit: () => void
  onCancelEdit: () => void
}>

export function DocumentDetailTagsPanel({
  editing,
  saveAction,
  saveButton,
  isSaving,
  tagsDraft,
  onTagsDraftChange,
  optimisticTags,
  tagsError,
  onBeginEdit,
  onCancelEdit,
}: DocumentDetailTagsPanelProps) {
  const commonT = useTranslations('Common')
  const t = useTranslations('DocumentDetailDialog')

  return (
    <Panel className="rounded-2xl">
      {editing ? (
        <form action={saveAction} className="space-y-4">
          <input type="hidden" name="tags_json" value={JSON.stringify(tagsDraft)} />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-3 min-w-0">
              <div className="grid h-10 w-10 place-items-center rounded-2xl border border-border bg-muted/40 text-muted-foreground">
                <Tags className="h-5 w-5" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-foreground">{t('tags.title')}</div>
                <div className="text-xs text-muted-foreground truncate">{t('tags.description')}</div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 justify-end">
              <Button type="button" variant="outline" size="sm" onClick={onCancelEdit} disabled={isSaving}>
                {commonT('cancel')}
              </Button>
              {saveButton}
            </div>
          </div>

          <div className="space-y-3">
            <TagInput value={tagsDraft} onValueChange={onTagsDraftChange} disabled={isSaving} />

            {tagsError ? (
              <Alert variant="destructive">
                <AlertTitle>{t('alerts.saveFailedTitle')}</AlertTitle>
                <AlertDescription>{tagsError}</AlertDescription>
              </Alert>
            ) : null}
          </div>
        </form>
      ) : (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-3 min-w-0">
              <div className="grid h-10 w-10 place-items-center rounded-2xl border border-border bg-muted/40 text-muted-foreground">
                <Tags className="h-5 w-5" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-foreground">{t('tags.title')}</div>
                <div className="text-xs text-muted-foreground truncate">{t('tags.description')}</div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 justify-end">
              <Button variant="outline" size="sm" className="gap-2" onClick={onBeginEdit}>
                <Pencil className="h-4 w-4" aria-hidden="true" />
                {t('actions.edit')}
              </Button>
            </div>
          </div>

          <div className="mt-4 space-y-3">
            {optimisticTags.length ? (
              <DocumentTags tags={optimisticTags} max={10} />
            ) : (
              <div className="text-xs text-muted-foreground">{t('tags.empty')}</div>
            )}

            {tagsError ? (
              <Alert variant="destructive">
                <AlertTitle>{t('alerts.saveFailedTitle')}</AlertTitle>
                <AlertDescription>{tagsError}</AlertDescription>
              </Alert>
            ) : null}
          </div>
        </>
      )}
    </Panel>
  )
}
