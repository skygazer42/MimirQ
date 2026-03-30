'use client'

import type { ComponentProps, ReactNode } from 'react'

import { Calendar, Pencil } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { Document } from '@/types'

type DocumentPublicationStatus = 'draft' | 'published' | 'deprecated'

type DocumentDetailLifecyclePanelProps = Readonly<{
  editing: boolean
  saveAction: ComponentProps<'form'>['action']
  saveButton: ReactNode
  isSaving: boolean
  canEdit: boolean
  editTitle?: string
  permissionAlertTitle: string
  validationAlertTitle: string
  lifecyclePermError: string | null
  lifecycleValidationError: string | null
  lifecycleError: string | null
  lifecyclePublicationStatusDraft: DocumentPublicationStatus
  onLifecyclePublicationStatusDraftChange: (next: DocumentPublicationStatus) => void
  lifecycleOwnerDraft: string
  onLifecycleOwnerDraftChange: (next: string) => void
  lifecycleReviewDueDraft: string
  onLifecycleReviewDueDraftChange: (next: string) => void
  lifecycleAuthorityDraft: string
  onLifecycleAuthorityDraftChange: (next: string) => void
  lifecycleSupersedesDraft: string
  onLifecycleSupersedesDraftChange: (next: string) => void
  displayDoc: Document
  onBeginEdit: () => void
  onCancelEdit: () => void
}>

export function DocumentDetailLifecyclePanel({
  editing,
  saveAction,
  saveButton,
  isSaving,
  canEdit,
  editTitle,
  permissionAlertTitle,
  validationAlertTitle,
  lifecyclePermError,
  lifecycleValidationError,
  lifecycleError,
  lifecyclePublicationStatusDraft,
  onLifecyclePublicationStatusDraftChange,
  lifecycleOwnerDraft,
  onLifecycleOwnerDraftChange,
  lifecycleReviewDueDraft,
  onLifecycleReviewDueDraftChange,
  lifecycleAuthorityDraft,
  onLifecycleAuthorityDraftChange,
  lifecycleSupersedesDraft,
  onLifecycleSupersedesDraftChange,
  displayDoc,
  onBeginEdit,
  onCancelEdit,
}: DocumentDetailLifecyclePanelProps) {
  const commonT = useTranslations('Common')
  const t = useTranslations('DocumentDetailDialog')

  return (
    <Panel className="rounded-2xl">
      {editing ? (
        <form action={saveAction}>
          <input type="hidden" name="publication_status" value={lifecyclePublicationStatusDraft} />

          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-3 min-w-0">
              <div className="grid h-10 w-10 place-items-center rounded-2xl border border-border bg-warning/10 text-warning">
                <Calendar className="h-5 w-5" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-foreground">{t('lifecycle.title')}</div>
                <div className="text-xs text-muted-foreground truncate">{t('lifecycle.description')}</div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 justify-end">
              <Button type="button" variant="outline" size="sm" onClick={onCancelEdit} disabled={isSaving}>
                {commonT('cancel')}
              </Button>
              {saveButton}
            </div>
          </div>

          <div className="mt-4 space-y-3">
            {lifecyclePermError ? (
              <Alert variant="destructive">
                <AlertTitle>{permissionAlertTitle}</AlertTitle>
                <AlertDescription>{lifecyclePermError}</AlertDescription>
              </Alert>
            ) : null}

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">{t('lifecycle.fields.publicationStatus.label')}</div>
                <Select
                  value={lifecyclePublicationStatusDraft}
                  onValueChange={(v) =>
                    onLifecyclePublicationStatusDraftChange(v === 'draft' || v === 'deprecated' ? v : 'published')
                  }
                  disabled={isSaving}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t('lifecycle.fields.publicationStatus.placeholder')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="published">{t('lifecycle.fields.publicationStatus.options.published')}</SelectItem>
                    <SelectItem value="draft">{t('lifecycle.fields.publicationStatus.options.draft')}</SelectItem>
                    <SelectItem value="deprecated">{t('lifecycle.fields.publicationStatus.options.deprecated')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">{t('lifecycle.fields.owner.label')}</div>
                <Input
                  name="lifecycle_owner"
                  value={lifecycleOwnerDraft}
                  onChange={(e) => onLifecycleOwnerDraftChange(e.target.value)}
                  placeholder={t('lifecycle.fields.owner.placeholder')}
                  disabled={isSaving}
                />
              </div>

              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">{t('lifecycle.fields.reviewDueAt.label')}</div>
                <Input
                  name="review_due_at"
                  type="datetime-local"
                  value={lifecycleReviewDueDraft}
                  onChange={(e) => onLifecycleReviewDueDraftChange(e.target.value)}
                  disabled={isSaving}
                />
              </div>

              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">{t('lifecycle.fields.authorityLevel.label')}</div>
                <Input
                  name="authority_level"
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  value={lifecycleAuthorityDraft}
                  onChange={(e) => onLifecycleAuthorityDraftChange(e.target.value)}
                  placeholder={t('lifecycle.fields.authorityLevel.placeholder')}
                  disabled={isSaving}
                />
              </div>

              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">{t('lifecycle.fields.supersedesDocumentId.label')}</div>
                <Input
                  name="supersedes_document_id"
                  value={lifecycleSupersedesDraft}
                  onChange={(e) => onLifecycleSupersedesDraftChange(e.target.value)}
                  placeholder={t('lifecycle.fields.supersedesDocumentId.placeholder')}
                  disabled={isSaving}
                />
              </div>
            </div>

            {lifecycleValidationError ? (
              <Alert variant="destructive">
                <AlertTitle>{validationAlertTitle}</AlertTitle>
                <AlertDescription>{lifecycleValidationError}</AlertDescription>
              </Alert>
            ) : null}

            {lifecycleError ? (
              <Alert variant="destructive">
                <AlertTitle>{t('alerts.saveFailedTitle')}</AlertTitle>
                <AlertDescription>{lifecycleError}</AlertDescription>
              </Alert>
            ) : null}
          </div>
        </form>
      ) : (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-3 min-w-0">
              <div className="grid h-10 w-10 place-items-center rounded-2xl border border-border bg-warning/10 text-warning">
                <Calendar className="h-5 w-5" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-foreground">{t('lifecycle.title')}</div>
                <div className="text-xs text-muted-foreground truncate">{t('lifecycle.description')}</div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 justify-end">
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={onBeginEdit}
                disabled={!canEdit}
                title={editTitle}
              >
                <Pencil className="h-4 w-4" aria-hidden="true" />
                {t('actions.edit')}
              </Button>
            </div>
          </div>

          <div className="mt-4 space-y-3">
            {lifecyclePermError ? (
              <Alert variant="destructive">
                <AlertTitle>{permissionAlertTitle}</AlertTitle>
                <AlertDescription>{lifecyclePermError}</AlertDescription>
              </Alert>
            ) : null}

            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="text-muted-foreground">publication_status</span>
                <span className="min-w-0 truncate text-foreground" title={String(displayDoc.publication_status || 'published')}>
                  {String(displayDoc.publication_status || 'published')}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="text-muted-foreground">lifecycle_owner</span>
                <span className="min-w-0 truncate text-foreground" title={String(displayDoc.lifecycle_owner || '-')}>
                  {String(displayDoc.lifecycle_owner || '-')}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="text-muted-foreground">review_due_at</span>
                <span className="min-w-0 truncate text-foreground" title={displayDoc.review_due_at ? new Date(String(displayDoc.review_due_at)).toLocaleString('zh-CN') : '-'}>
                  {displayDoc.review_due_at ? new Date(String(displayDoc.review_due_at)).toLocaleString('zh-CN') : '-'}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="text-muted-foreground">authority_level</span>
                <span className="min-w-0 truncate text-foreground font-mono" title={displayDoc.authority_level == null ? '-' : String(displayDoc.authority_level)}>
                  {displayDoc.authority_level == null ? '-' : String(displayDoc.authority_level)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="text-muted-foreground">supersedes_document_id</span>
                <span className="min-w-0 truncate text-foreground font-mono" title={String(displayDoc.supersedes_document_id || '-')}>
                  {String(displayDoc.supersedes_document_id || '-')}
                </span>
              </div>

              {!displayDoc.lifecycle_owner &&
              !displayDoc.review_due_at &&
              displayDoc.authority_level == null &&
              !displayDoc.supersedes_document_id ? (
                <div className="text-xs text-muted-foreground">{t('lifecycle.empty')}</div>
              ) : null}
            </div>

            {lifecycleError ? (
              <Alert variant="destructive">
                <AlertTitle>{t('alerts.saveFailedTitle')}</AlertTitle>
                <AlertDescription>{lifecycleError}</AlertDescription>
              </Alert>
            ) : null}
          </div>
        </>
      )}
    </Panel>
  )
}
