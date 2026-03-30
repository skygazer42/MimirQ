'use client'

import { Loader2, Shield } from 'lucide-react'
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
  const { pending } = useFormStatus()

  return (
    <Button type="submit" disabled={pending}>
      {pending ? (
        <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
      ) : null}
      保存
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
}: Omit<DocumentAccessDialogProps, 'open' | 'action'>) {
  const { pending } = useFormStatus()

  return (
    <>
      <input type="hidden" name="access_mode" value={accessMode} />
      <input type="hidden" name="access_group_ids_json" value={JSON.stringify(accessGroupIds)} />

      <div className="mt-4 space-y-4">
        <div className="space-y-2">
          <div className="text-sm font-medium">模式</div>
          <Select
            value={accessMode}
            onValueChange={(value) => onAccessModeChange(value as DocumentAccessMode)}
            disabled={pending}
          >
            <SelectTrigger>
              <SelectValue placeholder="选择访问模式" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="inherit">继承数据集</SelectItem>
              <SelectItem value="only_me">仅我可见</SelectItem>
              <SelectItem value="partial_members">指定成员/组</SelectItem>
              <SelectItem value="all_team_members">团队成员</SelectItem>
            </SelectContent>
          </Select>
          <div className="text-xs text-muted-foreground">
            Owner：<span className="font-mono">{ownerId || '-'}</span>
          </div>
        </div>

        {accessMode === 'partial_members' ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <div className="text-sm font-medium">允许组（可选）</div>
              <GroupChipsInput
                value={accessGroupIds}
                onChange={onAccessGroupIdsChange}
                placeholder="选择组（组内成员将自动获得访问权限）"
              />
              <div className="text-xs text-muted-foreground">最多 200 个；仅支持当前租户已存在的组。</div>
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium">允许成员（每行一个 user_id）</div>
              <Textarea
                name="access_members_text"
                value={accessMembersText}
                onChange={(event) => onAccessMembersTextChange(event.target.value)}
                placeholder={'例如：\nalice\nbob\ncharlie'}
                disabled={pending}
              />
              <div className="text-xs text-muted-foreground">最多 200 个；仅支持当前租户已存在的成员。</div>
            </div>
          </div>
        ) : null}
      </div>

      <div className="mt-6 flex items-center justify-end gap-2">
        <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
          取消
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
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" className="w-full gap-2 sm:w-auto">
          <Shield className="h-4 w-4" />
          访问控制
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogTitle>文档访问控制</DialogTitle>
        <DialogDescription className="text-xs">
          用于“安全裁剪（security trimming）”：在数据集权限基础上进一步限制该文档的可见范围。
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
