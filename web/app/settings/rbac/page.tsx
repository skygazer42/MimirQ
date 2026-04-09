'use client'

import { useEffect, useMemo, useState } from 'react'
import { RefreshCw, ShieldCheck, Users } from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { SystemDataStrip } from '@/components/ui/system-data-strip'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'
import { rbacApi, type TenantMember } from '@/lib/api'
import { EmptyState } from '@/components/ui/empty-state'
import { systemDenseControls, systemPageTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'

const ROLE_OPTIONS = [
  { key: 'owner', label: '拥有者（owner）' },
  { key: 'admin', label: '管理员（admin）' },
  { key: 'auditor', label: '审计员（auditor）' },
  { key: 'editor', label: '编辑（editor）' },
  { key: 'dataset_operator', label: '数据集运维（dataset_operator）' },
  { key: 'viewer', label: '只读（viewer）' },
]
const DENSE_OUTLINE_BUTTON = systemDenseControls.outlineButton
const DENSE_PRIMARY_BUTTON = 'h-7 rounded-md px-2.5 text-[11px] font-semibold'
const DENSE_INPUT = systemDenseControls.input
const DENSE_SELECT_TRIGGER = 'h-7 rounded-md border-border/70 bg-background text-[11px]'
const DENSE_PANEL = systemWorkbenchTokens.panel

export default function SettingsRbacPage() {
  const [loading, setLoading] = useState(false)
  const [members, setMembers] = useState<TenantMember[]>([])
  const [roleDraft, setRoleDraft] = useState<Record<string, string>>({})
  const [savingIds, setSavingIds] = useState<Record<string, boolean>>({})
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const q = String(query || '').trim().toLowerCase()
    if (!q) return members
    return (members || []).filter((m) => {
      const uid = String(m.user_id || '').toLowerCase()
      const role = String(m.role || '').toLowerCase()
      return uid.includes(q) || role.includes(q)
    })
  }, [members, query])
  const savingCount = useMemo(
    () => Object.values(savingIds).filter(Boolean).length,
    [savingIds]
  )

  const stripItems = useMemo(
    () => [
      { label: '总成员', value: members.length, mono: true },
      { label: '筛选后', value: filtered.length, mono: true },
      { label: '保存中', value: savingCount, mono: true },
      {
        label: '列表状态',
        value: loading ? '加载中' : members.length ? '已就绪' : '无数据',
        tone: loading ? 'warning' : members.length ? 'success' : 'default',
      },
    ],
    [members.length, filtered.length, savingCount, loading]
  )

  async function refresh(): Promise<void> {
    setLoading(true)
    try {
      const res = await rbacApi.listTenantMembers({ limit: 500 })
      const items = Array.isArray(res.items) ? res.items : []
      setMembers(items)
      const nextDraft: Record<string, string> = {}
      for (const m of items) {
        const uid = String(m.user_id || '')
        if (!uid) continue
        nextDraft[uid] = String(m.role || 'viewer')
      }
      setRoleDraft(nextDraft)
    } catch (err) {
      toast.error(formatApiError(err, '加载成员失败（需要管理员权限）'))
    } finally {
      setLoading(false)
    }
  }

  async function saveRole(userId: string): Promise<void> {
    const uid = String(userId || '').trim()
    if (!uid) return
    const desired = String(roleDraft[uid] || '').trim() || 'viewer'
    setSavingIds((prev) => ({ ...prev, [uid]: true }))
    try {
      const updated = await rbacApi.patchTenantMemberRole(uid, { role: desired })
      setMembers((prev) => (prev || []).map((m) => (String(m.user_id || '') === uid ? updated : m)))
      const roleLabel = ROLE_OPTIONS.find((option) => option.key === desired)?.label ?? `角色键（${desired}）`
      toast.success(`已更新角色：${uid} -> ${roleLabel}`)
    } catch (err) {
      toast.error(formatApiError(err, '更新角色失败'))
    } finally {
      setSavingIds((prev) => ({ ...prev, [uid]: false }))
    }
  }

  useEffect(() => {
    detachPromise(refresh())
  }, [])

  return (
    <AppFrame>
      <PageScaffold
        title="成员权限（RBAC）"
        description="基于角色访问控制（RBAC）管理租户成员角色（role），控制数据集与连接器的读写能力。"
        icon={ShieldCheck}
        iconColor="text-success"
        size="full"
        density="system-dense"
        top={<SystemDataStrip items={stripItems} minColumnWidth={148} />}
        actions={
          <Button variant="outline" size="sm" className={DENSE_OUTLINE_BUTTON} disabled={loading} onClick={() => detachPromise(refresh())}>
            <RefreshCw className={cn('size-4', loading && 'animate-spin motion-reduce:animate-none')} />
            刷新
          </Button>
        }
      >
        <div className="grid grid-cols-1 gap-4">
          <Panel padding="md" className={DENSE_PANEL}>
            <div className={cn('mb-3 flex items-center gap-2 text-sm', systemPageTokens.heading)}>
                <Users className="size-5" />
                成员列表
            </div>
            <div className="space-y-3">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div className="w-full space-y-1 sm:max-w-sm">
                  <Label className={systemPageTokens.microLabel}>搜索</Label>
                  <Input className={DENSE_INPUT} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="按用户 ID（user_id）/ 角色键（role）过滤" />
                </div>
                <Badge variant="outline" className="w-fit font-mono text-[10px]">
                  可见 {filtered.length} 人
                </Badge>
              </div>

              <div className="overflow-hidden rounded-lg border border-border/70">
                <div className={cn('grid grid-cols-12 bg-muted/40 px-3 py-2', systemPageTokens.tableHead)}>
                  <div className="col-span-6">用户 ID（user_id）</div>
                  <div className="col-span-3">角色（role）</div>
                  <div className="col-span-1">当前</div>
                  <div className="col-span-2 text-right">操作</div>
                </div>

                {(filtered || []).length ? (
                  (filtered || []).map((m) => {
                    const uid = String(m.user_id || '').trim()
                    const key = uid || String(m.id || '')
                    const draft = uid ? String(roleDraft[uid] || m.role || 'viewer') : String(m.role || 'viewer')
                    const saving = uid ? Boolean(savingIds[uid]) : false
                    return (
                      <div key={key} className="grid grid-cols-12 items-center gap-2 border-t border-border/70 px-3 py-1 text-[12px] transition-colors hover:bg-muted/20">
                        <div className="col-span-6 truncate font-mono text-[11px]" title={uid || '(无用户 ID / user_id)'}>{uid || '(无用户 ID / user_id)'}</div>
                        <div className="col-span-3">
                          <Select
                            value={draft}
                            onValueChange={(v) => {
                              if (!uid) return
                              setRoleDraft((prev) => ({ ...prev, [uid]: v }))
                            }}
                            disabled={!uid}
                          >
                            <SelectTrigger className={DENSE_SELECT_TRIGGER}>
                              <SelectValue placeholder="选择角色（role）" />
                            </SelectTrigger>
                            <SelectContent>
                              {ROLE_OPTIONS.map((r) => (
                                <SelectItem key={r.key} value={r.key}>
                                  {r.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="col-span-1">
                          {m.is_current ? (
                            <Badge variant="soft" className="font-mono text-[10px]">当前</Badge>
                          ) : (
                            <Badge variant="outline" className="font-mono text-[10px] text-muted-foreground">-</Badge>
                          )}
                        </div>
                        <div className="col-span-2 flex justify-end">
                          <Button
                            size="sm"
                            className={DENSE_PRIMARY_BUTTON}
                            disabled={!uid || saving}
                            onClick={() => detachPromise(saveRole(uid))}
                          >
                            保存
                          </Button>
                        </div>
                      </div>
                    )
                  })
                ) : (
                  loading ? (
                    <div className="px-3 py-8 text-sm text-muted-foreground">加载中…</div>
                  ) : (
                    <EmptyState
                      icon={Users}
                      title="暂无成员"
                      description="还没有添加任何成员，或您没有查看权限。"
                      className="rounded-none border-0 border-t border-border shadow-none"
                    />
                  )
                )}
              </div>
            </div>
          </Panel>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
