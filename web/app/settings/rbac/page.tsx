'use client'

import { useEffect, useMemo, useState } from 'react'
import { RefreshCw, ShieldCheck, Users } from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'
import { rbacApi, type TenantMember } from '@/lib/api'
import { EmptyState } from '@/components/ui/empty-state'

const ROLE_OPTIONS = [
    { key: 'owner', label: 'owner (admin)' },
    { key: 'admin', label: 'admin' },
    { key: 'auditor', label: 'auditor' },
    { key: 'editor', label: 'editor' },
    { key: 'dataset_operator', label: 'dataset_operator' },
    { key: 'viewer', label: 'viewer' },
]

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
      toast.error(formatApiError(err, '加载成员失败（需要 owner/admin 权限）'))
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
      toast.success(`已更新 ${uid} -> ${desired}`)
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
        title="RBAC（成员权限）"
        description="管理 tenant 成员角色（影响 datasets/connectors 的可写权限）"
        icon={ShieldCheck}
        iconColor="text-success"
        size="6xl"
        actions={
          <Button variant="outline" size="sm" className="gap-2 rounded-xl" disabled={loading} onClick={() => detachPromise(refresh())}>
            <RefreshCw className={cn('size-4', loading && 'animate-spin motion-reduce:animate-none')} />
            刷新
          </Button>
        }
      >
        <div className="grid grid-cols-1 gap-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Users className="size-5" />
                Tenant Members
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label>搜索</Label>
                  <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="按 user_id / role 过滤" />
                </div>
              </div>

              <div className="rounded-2xl border border-border overflow-hidden">
                <div className="grid grid-cols-12 text-xs font-semibold text-muted-foreground bg-muted/40 px-3 py-2">
                  <div className="col-span-5">user_id</div>
                  <div className="col-span-3">role</div>
                  <div className="col-span-2">current</div>
                  <div className="col-span-2 text-right">actions</div>
                </div>

                {(filtered || []).length ? (
                  (filtered || []).map((m) => {
                    const uid = String(m.user_id || '').trim()
                    const key = uid || String(m.id || '')
                    const draft = uid ? String(roleDraft[uid] || m.role || 'viewer') : String(m.role || 'viewer')
                    const saving = uid ? Boolean(savingIds[uid]) : false
                    return (
                      <div key={key} className="grid grid-cols-12 px-3 py-2 text-sm border-t border-border items-center gap-2">
                        <div className="col-span-5 font-mono text-xs truncate">{uid || '(no user_id)'}</div>
                        <div className="col-span-3">
                          <Select
                            value={draft}
                            onValueChange={(v) => {
                              if (!uid) return
                              setRoleDraft((prev) => ({ ...prev, [uid]: v }))
                            }}
                            disabled={!uid}
                          >
                            <SelectTrigger className="h-9 rounded-xl">
                              <SelectValue placeholder="role" />
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
                        <div className="col-span-2">
                          {m.is_current ? (
                            <span className="text-success font-semibold">yes</span>
                          ) : (
                            <span className="text-muted-foreground">no</span>
                          )}
                        </div>
                        <div className="col-span-2 flex justify-end">
                          <Button
                            size="sm"
                            className="rounded-xl"
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
                    <div className="px-3 py-8 text-sm text-muted-foreground">加载中...</div>
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
            </CardContent>
          </Card>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}

