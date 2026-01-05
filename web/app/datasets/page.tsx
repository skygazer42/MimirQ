'use client'

import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Layers, Loader2, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'

import { Navbar } from '@/components/navbar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { datasetApi } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import type { Dataset, PermissionEnum } from '@/types'

type DatasetFormState = {
  name: string
  description: string
  permission: PermissionEnum
  partialMembersText: string
}

function permissionLabel(p: PermissionEnum) {
  if (p === 'only_me') return '仅自己'
  if (p === 'partial_members') return '部分成员'
  return '全员'
}

function permissionBadgeVariant(p: PermissionEnum): 'default' | 'secondary' | 'outline' {
  if (p === 'only_me') return 'secondary'
  if (p === 'partial_members') return 'outline'
  return 'default'
}

function parseMembers(text: string): string[] {
  return (text || '')
    .split(/[\n,]/g)
    .map((s) => s.trim())
    .filter(Boolean)
}

export default function DatasetsPage() {
  const [items, setItems] = useState<Dataset[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(false)

  const [createOpen, setCreateOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<Dataset | null>(null)

  const [form, setForm] = useState<DatasetFormState>({
    name: '',
    description: '',
    permission: 'all_team_members',
    partialMembersText: '',
  })

  const resetForm = () => {
    setForm({
      name: '',
      description: '',
      permission: 'all_team_members',
      partialMembersText: '',
    })
  }

  const load = async () => {
    setIsLoading(true)
    try {
      const res = await datasetApi.list({ skip: 0, limit: 200 })
      setItems(res.items || [])
      setTotal(Number(res.total || 0))
    } catch (e: any) {
      console.error('Failed to load datasets', e)
      toast.error(e?.response?.data?.detail || e?.message || '加载数据集失败')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const canSubmit = useMemo(() => form.name.trim().length > 0, [form.name])

  const buildPayload = () => {
    const payload: any = {
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      permission: form.permission,
    }
    if (form.permission === 'partial_members') {
      payload.partial_member_list = parseMembers(form.partialMembersText)
    }
    return payload
  }

  const handleCreate = async () => {
    if (!canSubmit) return
    try {
      await datasetApi.create(buildPayload())
      toast.success('已创建数据集')
      setCreateOpen(false)
      resetForm()
      await load()
    } catch (e: any) {
      console.error('Failed to create dataset', e)
      toast.error(e?.response?.data?.detail || e?.message || '创建失败')
    }
  }

  const openEdit = (ds: Dataset) => {
    setEditing(ds)
    setForm({
      name: ds.name || '',
      description: ds.description || '',
      permission: ds.permission || 'all_team_members',
      partialMembersText: (ds.partial_member_list || []).join('\n'),
    })
    setEditOpen(true)
  }

  const handleUpdate = async () => {
    if (!editing?.id) return
    if (!canSubmit) return
    try {
      await datasetApi.update(editing.id, buildPayload())
      toast.success('已更新数据集')
      setEditOpen(false)
      setEditing(null)
      resetForm()
      await load()
    } catch (e: any) {
      console.error('Failed to update dataset', e)
      toast.error(e?.response?.data?.detail || e?.message || '更新失败')
    }
  }

  const handleDelete = async (ds: Dataset) => {
    if (!ds?.id) return
    if (!confirm(`确定删除数据集 “${ds.name}” 吗？此操作不可恢复。`)) return
    try {
      await datasetApi.delete(ds.id)
      toast.success('已删除数据集')
      setItems((prev) => prev.filter((x) => x.id !== ds.id))
      setTotal((prev) => Math.max(0, prev - 1))
    } catch (e: any) {
      console.error('Failed to delete dataset', e)
      toast.error(e?.response?.data?.detail || e?.message || '删除失败')
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50/50 dark:bg-slate-950 transition-colors duration-300">
      <Navbar />

      <main className="flex-1 flex flex-col overflow-hidden relative">
        <div className="absolute top-0 left-0 right-0 h-64 bg-gradient-to-b from-indigo-50/50 dark:from-indigo-900/10 to-transparent pointer-events-none" />

        <header className="px-8 py-6 flex-shrink-0 z-10">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-white dark:bg-slate-900 rounded-2xl flex items-center justify-center shadow-sm border border-slate-100 dark:border-slate-800">
                <Layers className="w-6 h-6 text-indigo-600 dark:text-indigo-400" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">数据集</h1>
                <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">管理知识库集合与访问权限</p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                className="gap-2 rounded-xl"
                onClick={() => load()}
                disabled={isLoading}
              >
                <RefreshCw className={cn('w-4 h-4', isLoading && 'animate-spin')} />
                刷新
              </Button>

              <Dialog open={createOpen} onOpenChange={(open) => {
                setCreateOpen(open)
                if (open) resetForm()
              }}>
                <DialogTrigger asChild>
                  <Button className="gap-2 bg-indigo-600 hover:bg-indigo-700 text-white shadow-lg shadow-indigo-200 dark:shadow-indigo-900/20 rounded-xl">
                    <Plus className="w-4 h-4" />
                    新建数据集
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-xl">
                  <DialogHeader>
                    <DialogTitle>新建数据集</DialogTitle>
                    <DialogDescription>为文档分组并设置访问权限</DialogDescription>
                  </DialogHeader>

                  <DatasetForm form={form} setForm={setForm} />

                  <DialogFooter>
                    <Button variant="outline" onClick={() => setCreateOpen(false)}>取消</Button>
                    <Button onClick={handleCreate} disabled={!canSubmit}>创建</Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
          </div>

          <div className="mt-4 text-sm text-slate-500 dark:text-slate-400">
            共 <span className="font-semibold text-slate-700 dark:text-slate-200">{total}</span> 个数据集
          </div>
        </header>

        <section className="flex-1 overflow-y-auto px-8 pb-8">
          <div className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm border border-slate-200 dark:border-slate-800 rounded-2xl overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
              <div className="text-sm font-semibold text-slate-800 dark:text-slate-200">数据集列表</div>
              {isLoading && (
                <div className="flex items-center gap-2 text-sm text-slate-500">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  加载中...
                </div>
              )}
            </div>

            {items.length === 0 && !isLoading ? (
              <div className="p-10 text-center text-slate-500 dark:text-slate-400">
                暂无数据集，点击“新建数据集”开始创建。
              </div>
            ) : (
              <div className="divide-y divide-slate-100 dark:divide-slate-800">
                {items.map((ds) => (
                  <div key={ds.id} className="px-6 py-4 flex items-start justify-between gap-4">
                    <div className="min-w-0">
                        <div className="flex items-center gap-3">
                        <div className="font-semibold text-slate-900 dark:text-white truncate">{ds.name}</div>
                        <Badge variant={permissionBadgeVariant(ds.permission)}>
                          {permissionLabel(ds.permission)}
                        </Badge>
                      </div>
                      {ds.description && (
                        <div className="mt-1 text-sm text-slate-500 dark:text-slate-400 line-clamp-2">
                          {ds.description}
                        </div>
                      )}
                      {ds.permission === 'partial_members' && (ds.partial_member_list || []).length > 0 && (
                        <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                          成员：{(ds.partial_member_list || []).slice(0, 6).join(', ')}
                          {(ds.partial_member_list || []).length > 6 ? ' ...' : ''}
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-2 flex-shrink-0">
                      <Button variant="outline" size="sm" className="gap-2" onClick={() => openEdit(ds)}>
                        <Pencil className="w-4 h-4" />
                        编辑
                      </Button>
                      <Button variant="destructive" size="sm" className="gap-2" onClick={() => handleDelete(ds)}>
                        <Trash2 className="w-4 h-4" />
                        删除
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        <Dialog open={editOpen} onOpenChange={(open) => {
          setEditOpen(open)
          if (!open) {
            setEditing(null)
            resetForm()
          }
        }}>
          <DialogContent className="max-w-xl">
            <DialogHeader>
              <DialogTitle>编辑数据集</DialogTitle>
              <DialogDescription>更新名称、描述与访问权限</DialogDescription>
            </DialogHeader>

            <DatasetForm form={form} setForm={setForm} />

            <DialogFooter>
              <Button variant="outline" onClick={() => setEditOpen(false)}>取消</Button>
              <Button onClick={handleUpdate} disabled={!canSubmit || !editing}>保存</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </main>
    </div>
  )
}

function DatasetForm({
  form,
  setForm,
}: {
  form: DatasetFormState
  setForm: (next: DatasetFormState) => void
}) {
  return (
    <div className="grid gap-4">
      <div className="grid gap-2">
        <Label htmlFor="ds-name">名称</Label>
        <Input
          id="ds-name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="例如：产品文档 / 技术周报 / 合同资料"
        />
      </div>

      <div className="grid gap-2">
        <Label htmlFor="ds-desc">描述（可选）</Label>
        <Textarea
          id="ds-desc"
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="用于说明该数据集包含哪些文档、用途是什么..."
          className="min-h-[96px]"
        />
      </div>

      <div className="grid gap-2">
        <Label>权限</Label>
        <Select value={form.permission} onValueChange={(v) => setForm({ ...form, permission: v as PermissionEnum })}>
          <SelectTrigger>
            <SelectValue placeholder="选择权限" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all_team_members">全员可见</SelectItem>
            <SelectItem value="only_me">仅自己</SelectItem>
            <SelectItem value="partial_members">部分成员</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {form.permission === 'partial_members' && (
        <div className="grid gap-2">
          <Label htmlFor="ds-members">成员列表（account_id，一行一个或逗号分隔）</Label>
          <Textarea
            id="ds-members"
            value={form.partialMembersText}
            onChange={(e) => setForm({ ...form, partialMembersText: e.target.value })}
            placeholder="user_1\nuser_2"
            className="min-h-[96px]"
          />
        </div>
      )}
    </div>
  )
}
