'use client'

import { useId, useRef, useState, type FormEvent } from 'react'
import { useTranslations } from 'next-intl'

import { Shield } from '@/components/icons'
import { GroupChipsInput } from '@/components/groups/group-chips-input'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { LoadingButton } from '@/components/ui/loading-button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { documentAccessModeSchema } from '@/lib/document-access-schema'
import { formatApiError } from '@/lib/api-errors'
import type { DocumentAccessInfo, DocumentAccessUpdateRequest } from '@/types/documents'

type DocumentAccessDialogProps = Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  access: DocumentAccessInfo | undefined
  loading: boolean
  loadError: string | null
  isSaving: boolean
  metadataBusy: boolean
  onRetry: () => void
  onSave: (payload: DocumentAccessUpdateRequest) => Promise<'saved' | 'skipped'>
}>

type AccessDraft = {
  mode: DocumentAccessInfo['mode']
  groupIds: string[]
  membersText: string
}

type AccessEditor = {
  draft: AccessDraft
  error: string | null
}

type DocumentAccessFormProps = Pick<
  DocumentAccessDialogProps,
  'onOpenChange' | 'isSaving' | 'metadataBusy' | 'onSave' | 'loading' | 'loadError'
> & { access: DocumentAccessInfo }

function createAccessDraft(access: DocumentAccessInfo): AccessDraft {
  return {
    mode: access.mode,
    groupIds: [...new Set(access.partial_group_list)],
    membersText:
      access.partial_member_list === null || access.partial_member_list === undefined
        ? ''
        : access.partial_member_list.join('\n'),
  }
}

function DocumentAccessForm({
  access,
  onOpenChange,
  isSaving,
  metadataBusy,
  loading,
  loadError,
  onSave,
}: DocumentAccessFormProps) {
  const t = useTranslations('DocumentAccessDialog')
  const formId = useId()
  const [editor, setEditor] = useState<AccessEditor | null>(null)
  const submittingRef = useRef(false)
  const accessReady = !loading && loadError === null
  const controlsDisabled = metadataBusy || !accessReady
  const draft = editor === null ? (accessReady ? createAccessDraft(access) : null) : editor.draft

  if (draft === null) return null
  const isPartial = draft.mode === 'partial_members'

  const changeDraft = (change: Partial<AccessDraft>) => {
    setEditor((current) => ({
      draft: { ...(current === null ? draft : current.draft), ...change },
      error: null,
    }))
  }

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (controlsDisabled || submittingRef.current) return
    const payload: DocumentAccessUpdateRequest = {
      mode: draft.mode,
      partial_member_list: null,
      partial_group_list: null,
    }
    if (isPartial) {
      const members = Array.from(
        new Set(
          draft.membersText
            .split(/[\n,;]+/)
            .map((member) => member.trim())
            .filter((member) => member.length > 0),
        ),
      )
      if (members.length > 200 || draft.groupIds.length > 200) {
        setEditor({ draft, error: t('errors.limit') })
        return
      }
      payload.partial_member_list = members
      payload.partial_group_list = draft.groupIds
    }

    const submission: AccessEditor = { draft, error: null }
    submittingRef.current = true
    setEditor(submission)
    try {
      await onSave(payload)
    } catch (saveError) {
      const error = formatApiError(saveError, t('errors.save'))
      setEditor((current) => (current === submission ? { ...submission, error } : current))
    } finally {
      submittingRef.current = false
    }
  }

  return (
    <form onSubmit={save} className="mt-4 space-y-4">
      <fieldset disabled={controlsDisabled} className="min-w-0 space-y-4">
        <div className="space-y-2">
          <Label htmlFor={`${formId}-mode`}>{t('mode.label')}</Label>
          <Select
            value={draft.mode}
            onValueChange={(value) => changeDraft({ mode: documentAccessModeSchema.parse(value) })}
            disabled={controlsDisabled}
          >
            <SelectTrigger id={`${formId}-mode`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="inherit">{t('mode.options.inherit')}</SelectItem>
              <SelectItem value="only_me">{t('mode.options.onlyMe')}</SelectItem>
              <SelectItem value="partial_members">{t('mode.options.partialMembers')}</SelectItem>
              <SelectItem value="all_team_members">{t('mode.options.allTeamMembers')}</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            {t('ownerLabel')}：
            <span className="font-mono">
              {access.owner_id === null || access.owner_id === undefined ? t('ownerNotSet') : access.owner_id}
            </span>
          </p>
        </div>

        {isPartial ? (
          <>
            <div className="space-y-2">
              <Label htmlFor={`${formId}-groups`}>{t('groups.label')}</Label>
              <GroupChipsInput
                id={`${formId}-groups`}
                value={draft.groupIds}
                onChange={(groupIds) => changeDraft({ groupIds })}
                placeholder={t('groups.placeholder')}
                disabled={controlsDisabled}
              />
              <p className="text-xs text-muted-foreground">{t('groups.hint')}</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${formId}-members`}>{t('members.label')}</Label>
              <Textarea
                id={`${formId}-members`}
                aria-describedby={`${formId}-members-hint`}
                value={draft.membersText}
                onChange={(event) => changeDraft({ membersText: event.target.value })}
                placeholder={t('members.placeholder')}
              />
              <p id={`${formId}-members-hint`} className="text-xs text-muted-foreground">
                {t('members.hint')}
              </p>
            </div>
          </>
        ) : null}
      </fieldset>
      {editor !== null && editor.error !== null ? (
        <p role="alert" className="text-sm text-destructive">
          {editor.error}
        </p>
      ) : null}
      <div className="flex items-center justify-end gap-2 pt-2">
        <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isSaving}>
          {t('actions.cancel')}
        </Button>
        <LoadingButton type="submit" loading={isSaving} disabled={controlsDisabled}>
          {t('actions.save')}
        </LoadingButton>
      </div>
    </form>
  )
}

export function DocumentAccessDialog({
  open,
  onOpenChange,
  access,
  loading,
  loadError,
  isSaving,
  metadataBusy,
  onRetry,
  onSave,
}: DocumentAccessDialogProps) {
  const t = useTranslations('DocumentAccessDialog')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" className="w-full gap-2 sm:w-auto">
          <Shield className="h-4 w-4" aria-hidden="true" />
          {t('trigger')}
        </Button>
      </DialogTrigger>
      {open && (
        <DialogContent className="max-h-[90dvh] max-w-xl overflow-y-auto" showCloseButton={!isSaving}>
          <DialogTitle>{t('title')}</DialogTitle>
          <DialogDescription className="text-xs">{t('description')}</DialogDescription>
          {loading ? (
            <p role="status" className="mt-4 text-sm text-muted-foreground">
              {t('loading')}
            </p>
          ) : null}
          {loadError !== null ? (
            <div className="mt-4 space-y-2">
              <p role="alert" className="text-sm text-destructive">
                {loadError}
              </p>
              <Button type="button" variant="outline" size="sm" onClick={onRetry} disabled={loading}>
                {t('actions.retry')}
              </Button>
            </div>
          ) : null}
          {access !== undefined ? (
            <DocumentAccessForm
              access={access}
              onOpenChange={onOpenChange}
              isSaving={isSaving}
              metadataBusy={metadataBusy}
              loading={loading}
              loadError={loadError}
              onSave={onSave}
            />
          ) : null}
        </DialogContent>
      )}
    </Dialog>
  )
}
