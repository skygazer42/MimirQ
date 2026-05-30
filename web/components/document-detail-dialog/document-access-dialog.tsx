'use client'

import { Loader2, Shield } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { useFormStatus } from 'react-dom'

import { GroupChipsInput } from '@/components/groups/group-chips-input'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { DocumentAccessMode } from '@/types'

interface DocumentAccessDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  ownerId: string | null | undefined
  accessMode: DocumentAccessMode
  onAccessModeChange: (mode: DocumentAccessMode) => void
  accessGroupIds: string[]
  onAccessGroupIdsChange: (value: string[]) => void
  accessMembersText: string
  onAccessMembersTextChange: (value: string) => void
  action: (payload: FormData) => void
}

function DocumentAccessSaveButton() {
  const t = useTranslations('DocumentAccessDialog')
  const { pending } = useFormStatus()

  return (
    <Button type="submit" disabled={pending}>
      {pending ? (
        <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
      ) : null}
      {t('actions.save')}
    </Button>
  )
}

function DocumentAccessDialogForm({
  ownerId,
  accessMode,
  onAccessModeChange,
  accessGroupIds,
  onAccessGroupIdsChange,
  accessMembersText,
  onAccessMembersTextChange,
  onOpenChange,
}: Readonly<Omit<DocumentAccessDialogProps, 'open' | 'action'>>) {
  const t = useTranslations('DocumentAccessDialog')
  const { pending } = useFormStatus()

  return (
    <>
      <input type="hidden" name="access_mode" value={accessMode} />
      <input type="hidden" name="access_group_ids_json" value={JSON.stringify(accessGroupIds)} />

      <div className="mt-4 space-y-4">
        <div className="space-y-2">
          <div className="text-sm font-medium">{t('mode.label')}</div>
          <Select
            value={accessMode}
            onValueChange={(value) => onAccessModeChange(value as DocumentAccessMode)}
            disabled={pending}
          >
            <SelectTrigger>
              <SelectValue placeholder={t("mode.placeholder")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="inherit">{t('mode.options.inherit')}</SelectItem>
              <SelectItem value="only_me">{t('mode.options.onlyMe')}</SelectItem>
              <SelectItem value="partial_members">{t('mode.options.partialMembers')}</SelectItem>
              <SelectItem value="all_team_members">{t('mode.options.allTeamMembers')}</SelectItem>
            </SelectContent>
          </Select>
          <div className="text-xs text-muted-foreground">
            {t('ownerLabel')}：<span className="font-mono">{ownerId || '-'}</span>
          </div>
        </div>

        {accessMode === 'partial_members' ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <div className="text-sm font-medium">{t('groups.label')}</div>
              <GroupChipsInput
                value={accessGroupIds}
                onChange={onAccessGroupIdsChange}
                placeholder={t('groups.placeholder')}
              />
              <div className="text-xs text-muted-foreground">{t('groups.hint')}</div>
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium">{t('members.label')}</div>
              <Textarea
                name="access_members_text"
                value={accessMembersText}
                onChange={(event) => onAccessMembersTextChange(event.target.value)}
                placeholder={t('members.placeholder')}
                disabled={pending}
              />
              <div className="text-xs text-muted-foreground">{t('members.hint')}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div className="mt-6 flex items-center justify-end gap-2">
        <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
          {t('actions.cancel')}
        </Button>
        <DocumentAccessSaveButton />
      </div>
    </>
  )
}

export function DocumentAccessDialog({
  open,
  onOpenChange,
  ownerId,
  accessMode,
  onAccessModeChange,
  accessGroupIds,
  onAccessGroupIdsChange,
  accessMembersText,
  onAccessMembersTextChange,
  action,
}: Readonly<DocumentAccessDialogProps>) {
  const t = useTranslations('DocumentAccessDialog')
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" className="w-full gap-2 sm:w-auto">
          <Shield className="h-4 w-4" />
          {t("trigger")}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogTitle>{t('title')}</DialogTitle>
        <DialogDescription className="text-xs">
          {t('description')}
        </DialogDescription>
        <form action={action}>
          <DocumentAccessDialogForm
            ownerId={ownerId}
            accessMode={accessMode}
            onAccessModeChange={onAccessModeChange}
            accessGroupIds={accessGroupIds}
            onAccessGroupIdsChange={onAccessGroupIdsChange}
            accessMembersText={accessMembersText}
            onAccessMembersTextChange={onAccessMembersTextChange}
            onOpenChange={onOpenChange}
          />
        </form>
      </DialogContent>
    </Dialog>
  )
}
