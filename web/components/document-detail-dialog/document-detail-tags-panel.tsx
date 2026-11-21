'use client'

import { useId, type FormEvent } from 'react'

import { Pencil, Tags } from '@/components/icons'
import { useTranslations } from 'next-intl'

import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { Panel } from '@/components/ui/panel'
import { TagInput } from '@/components/ui/tag-input'
import { DocumentTags } from '@/components/documents/document-tags'
import { DOCUMENT_TAG_LENGTH, DOCUMENT_TAG_LIMIT } from '@/lib/document-user-tags'

type DocumentDetailTagsPanelProps = Readonly<{
  editing: boolean
  onSave: (event: FormEvent<HTMLFormElement>) => Promise<void>
  canSave: boolean
  isSaving: boolean
  tagsDraft: string[]
  onTagsDraftChange: (next: string[]) => void
  tags: string[]
  tagsError: string | null
  onBeginEdit: () => void
  onCancelEdit: () => void
}>

export function DocumentDetailTagsPanel({
  editing,
  onSave,
  canSave,
  isSaving,
  tagsDraft,
  onTagsDraftChange,
  tags,
  tagsError,
  onBeginEdit,
  onCancelEdit,
}: DocumentDetailTagsPanelProps) {
  const commonT = useTranslations('Common')
  const t = useTranslations('DocumentDetailDialog')
  const formId = useId()
  const tagInputId = `${formId}-input`

  return (
    <Panel className="rounded-2xl">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl border border-border bg-muted/40 text-muted-foreground">
            <Tags className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-foreground">{t('tags.title')}</h3>
            <p className="text-xs text-muted-foreground">{t('tags.description')}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {editing ? (
            <>
              <Button type="button" variant="outline" size="sm" onClick={onCancelEdit} disabled={isSaving}>
                {commonT('cancel')}
              </Button>
              <LoadingButton type="submit" form={formId} size="sm" loading={isSaving} disabled={!canSave}>
                {commonT('save')}
              </LoadingButton>
            </>
          ) : (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={onBeginEdit}
              disabled={isSaving}
            >
              <Pencil className="h-4 w-4" aria-hidden="true" />
              {t('actions.edit')}
            </Button>
          )}
        </div>
      </div>
      {editing ? (
        <form id={formId} onSubmit={onSave} className="mt-4 space-y-3">
          <label htmlFor={tagInputId} className="sr-only">
            {t('tags.title')}
          </label>
          <TagInput
            inputId={tagInputId}
            value={tagsDraft}
            onValueChange={onTagsDraftChange}
            maxTags={DOCUMENT_TAG_LIMIT}
            maxTagLen={DOCUMENT_TAG_LENGTH}
            disabled={isSaving}
          />
          {tagsError !== null && (
            <p role="alert" className="break-words text-sm text-destructive">
              {tagsError}
            </p>
          )}
        </form>
      ) : (
        <div className="mt-4">
          {tags.length > 0 ? (
            <DocumentTags tags={tags} />
          ) : (
            <p className="text-xs text-muted-foreground">{t('tags.empty')}</p>
          )}
        </div>
      )}
    </Panel>
  )
}
