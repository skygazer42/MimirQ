'use client'

import { useId, useState, type FormEvent } from 'react'
import { useTranslations } from 'next-intl'

import { Calendar, Pencil } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { LoadingButton } from '@/components/ui/loading-button'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatApiError } from '@/lib/api-errors'
import {
  buildLifecyclePatch,
  createLifecycleDraft,
  getLifecycleValidationKey,
  publicationStatusSchema,
  type LifecycleDraft,
} from '@/lib/document-lifecycle'
import type { Document } from '@/types/documents'
import type { DocumentLifecycleMetadata, DocumentLifecycleMetadataUpdateRequest } from '@/types/processing'

type LifecycleEditor = {
  baseline: DocumentLifecycleMetadata
  draft: LifecycleDraft
  error: string | null
}

type DocumentDetailLifecyclePanelProps = Readonly<{
  document: Partial<
    Pick<
      Document,
      'publication_status' | 'lifecycle_owner' | 'review_due_at' | 'authority_level' | 'supersedes_document_id'
    >
  >
  metadata: DocumentLifecycleMetadata | undefined
  canEdit: boolean
  loading: boolean
  loadError: string | null
  isSaving: boolean
  metadataBusy: boolean
  onRetry: () => void
  onSave: (patch: DocumentLifecycleMetadataUpdateRequest) => Promise<'saved' | 'skipped'>
}>

export function DocumentDetailLifecyclePanel({
  document,
  metadata,
  canEdit,
  loading,
  loadError,
  isSaving,
  metadataBusy,
  onRetry,
  onSave,
}: DocumentDetailLifecyclePanelProps) {
  const t = useTranslations('DocumentDetailDialog')
  const commonT = useTranslations('Common')
  const formId = useId()
  const [editor, setEditor] = useState<LifecycleEditor | null>(null)
  const validationKey = editor === null ? null : getLifecycleValidationKey(editor.draft)
  const patch = editor === null || validationKey !== null ? null : buildLifecyclePatch(editor.baseline, editor.draft)
  const canEditMetadata = metadata !== undefined && canEdit && !loading && !metadataBusy
  const canSave = canEditMetadata && patch !== null && Object.keys(patch).length > 0
  const current = metadata === undefined ? document : metadata
  const publicationStatus = current.publication_status
  const rows = [
    {
      key: 'publication_status',
      label: t('lifecycle.fields.publicationStatus.label'),
      value:
        publicationStatus === undefined
          ? undefined
          : t(`lifecycle.fields.publicationStatus.options.${publicationStatus}`),
    },
    { key: 'lifecycle_owner', label: t('lifecycle.fields.owner.label'), value: current.lifecycle_owner },
    {
      key: 'review_due_at',
      label: t('lifecycle.fields.reviewDueAt.label'),
      value:
        current.review_due_at === null || current.review_due_at === undefined
          ? null
          : new Date(current.review_due_at).toLocaleString('zh-CN'),
      title: current.review_due_at === null ? undefined : current.review_due_at,
    },
    { key: 'authority_level', label: t('lifecycle.fields.authorityLevel.label'), value: current.authority_level },
    {
      key: 'supersedes_document_id',
      label: t('lifecycle.fields.supersedesDocumentId.label'),
      value: current.supersedes_document_id,
    },
  ]

  function beginEdit() {
    if (!canEditMetadata) return
    setEditor({ baseline: metadata, draft: createLifecycleDraft(metadata), error: null })
  }

  function changeDraft(change: Partial<LifecycleDraft>) {
    setEditor((currentEditor) =>
      currentEditor === null
        ? null
        : {
            ...currentEditor,
            draft: { ...currentEditor.draft, ...change },
            error: null,
          },
    )
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSave || editor === null) return
    try {
      const result = await onSave(patch)
      if (result === 'saved') setEditor((currentEditor) => (currentEditor === editor ? null : currentEditor))
    } catch (error) {
      const message = formatApiError(error, t('errors.saveLifecycleFailed'))
      setEditor((currentEditor) => (currentEditor === editor ? { ...editor, error: message } : currentEditor))
    }
  }

  return (
    <Panel className="rounded-2xl">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl border border-border bg-warning/10 text-warning">
            <Calendar className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-foreground">{t('lifecycle.title')}</h3>
            <p className="text-xs text-muted-foreground">{t('lifecycle.description')}</p>
          </div>
        </div>
        {editor === null ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="gap-2 self-end"
            onClick={beginEdit}
            disabled={!canEditMetadata}
          >
            <Pencil className="h-4 w-4" aria-hidden="true" />
            {t('actions.edit')}
          </Button>
        ) : (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => setEditor(null)} disabled={isSaving}>
              {commonT('cancel')}
            </Button>
            <LoadingButton type="submit" form={formId} size="sm" loading={isSaving} disabled={!canSave}>
              {commonT('save')}
            </LoadingButton>
          </div>
        )}
      </div>
      {loading ? (
        <p role="status" className="mt-3 text-xs text-muted-foreground">
          {t('lifecycle.permissionChecking')}
        </p>
      ) : null}
      {loadError !== null ? (
        <div className="mt-3 space-y-2">
          <p role="alert" className="break-words text-sm text-destructive">
            {loadError}
          </p>
          <Button type="button" variant="outline" size="sm" onClick={onRetry} disabled={loading}>
            {t('lifecycle.retry')}
          </Button>
        </div>
      ) : null}
      {editor === null ? (
        <dl className="mt-4 space-y-1.5">
          {rows.map(({ key, label, value, title }) => (
            <div key={key} className="flex items-start justify-between gap-3 text-xs">
              <dt className="shrink-0 text-muted-foreground">{label}</dt>
              <dd className="min-w-0 break-words text-right text-foreground" title={title}>
                {value === null || value === undefined ? t('lifecycle.notProvided') : value}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <form id={formId} onSubmit={save} className="mt-4 space-y-3">
          <fieldset disabled={isSaving || !canEdit} className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor={`${formId}-publication`}>{t('lifecycle.fields.publicationStatus.label')}</Label>
              <Select
                value={editor.draft.publicationStatus}
                onValueChange={(value) => changeDraft({ publicationStatus: publicationStatusSchema.parse(value) })}
                disabled={isSaving || !canEdit}
              >
                <SelectTrigger id={`${formId}-publication`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {publicationStatusSchema.options.map((value) => (
                    <SelectItem key={value} value={value}>
                      {t(`lifecycle.fields.publicationStatus.options.${value}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${formId}-owner`}>{t('lifecycle.fields.owner.label')}</Label>
              <Input
                id={`${formId}-owner`}
                name="lifecycle_owner"
                value={editor.draft.owner}
                onChange={(event) => changeDraft({ owner: event.target.value })}
                placeholder={t('lifecycle.fields.owner.placeholder')}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${formId}-review`}>{t('lifecycle.fields.reviewDueAt.label')}</Label>
              <Input
                id={`${formId}-review`}
                name="review_due_at"
                type="datetime-local"
                step="any"
                value={editor.draft.reviewDueAt}
                onChange={(event) => changeDraft({ reviewDueAt: event.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${formId}-authority`}>{t('lifecycle.fields.authorityLevel.label')}</Label>
              <Input
                id={`${formId}-authority`}
                name="authority_level"
                type="number"
                min={0}
                max={100}
                step={1}
                value={editor.draft.authorityLevel}
                onChange={(event) => changeDraft({ authorityLevel: event.target.value })}
                placeholder={t('lifecycle.fields.authorityLevel.placeholder')}
                aria-invalid={
                  validationKey === 'validation.authorityInteger' || validationKey === 'validation.authorityRange'
                }
              />
            </div>
            <div className="space-y-1.5 md:col-span-2">
              <Label htmlFor={`${formId}-supersedes`}>{t('lifecycle.fields.supersedesDocumentId.label')}</Label>
              <Input
                id={`${formId}-supersedes`}
                name="supersedes_document_id"
                value={editor.draft.supersedesDocumentId}
                onChange={(event) => changeDraft({ supersedesDocumentId: event.target.value })}
                placeholder={t('lifecycle.fields.supersedesDocumentId.placeholder')}
                aria-invalid={validationKey === 'validation.supersedesUuid'}
              />
            </div>
          </fieldset>
          {validationKey !== null ? (
            <p role="alert" className="break-words text-sm text-destructive">
              {t(validationKey)}
            </p>
          ) : null}
          {editor.error !== null ? (
            <p role="alert" className="break-words text-sm text-destructive">
              {editor.error}
            </p>
          ) : null}
        </form>
      )}
    </Panel>
  )
}
