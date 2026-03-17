'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Copy, Download, Plus, RefreshCw, ShieldCheck, Trash2, Upload } from 'lucide-react'
import { toast } from 'sonner'

import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { EmptyState } from '@/components/ui/empty-state'
import { pipelineApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'
import type { GovernanceProfileCreate, GovernanceProfileListResponse, GovernanceProfileSummary } from '@/types'
import { ProfileEditorDrawer } from '@/components/governance-profiles/profile-editor-drawer'
import { buildGovernanceProfileCreateFromExisting, buildIngestionPolicyExportFilename } from '@/lib/governance-profile-utils'

export function GovernanceProfilesPage() {
  const [loading, setLoading] = useState(false)
  const [resp, setResp] = useState<GovernanceProfileListResponse | null>(null)
  const [query, setQuery] = useState('')
  const [includeBuiltin, setIncludeBuiltin] = useState(true)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editorMode, setEditorMode] = useState<'create' | 'edit' | 'view'>('create')
  const [editorProfileRef, setEditorProfileRef] = useState<string | null>(null)
  const [editorSeedCreate, setEditorSeedCreate] = useState<GovernanceProfileCreate | null>(null)
  const [importing, setImporting] = useState(false)
  const [importOverwrite, setImportOverwrite] = useState(false)
  const importInputRef = useRef<HTMLInputElement | null>(null)

  const params = useMemo(() => {
    const q = query.trim()
    return {
      q: q || undefined,
      include_builtin: includeBuiltin,
      limit: 200,
    }
  }, [query, includeBuiltin])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await pipelineApi.listGovernanceProfiles(params)
      setResp(data)
    } catch (err: any) {
      setResp(null)
      toast.error(formatApiError(err, '加载治理 Profiles 失败'))
    } finally {
      setLoading(false)
    }
  }, [params])

  // Keep it simple: fetch on param change.
  useEffect(() => {
    detachPromise(load())
  }, [load])

  const items: GovernanceProfileSummary[] = resp?.items || []

  const exportOne = async (p: GovernanceProfileSummary) => {
    const ref = p.is_system ? p.key : String(p.id || '').trim() || p.key
    if (!ref) return
    try {
      const blob = await pipelineApi.exportGovernanceProfile(ref)
      const safe = (p.key || 'profile').replaceAll(/[\\/:*?"<>|]+/g, '_').slice(0, 120)
      const filename = `${safe}.governance-profile.json`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      toast.success('已导出')
    } catch (err: any) {
      toast.error(formatApiError(err, '导出失败'))
    }
  }

  const exportAsIngestionPolicy = async (p: GovernanceProfileSummary) => {
    const ref = p.is_system ? p.key : String(p.id || '').trim() || p.key
    if (!ref) return
    try {
      const blob = await pipelineApi.exportGovernanceProfileIngestionPolicy(ref)
      const filename = buildIngestionPolicyExportFilename(p.key || 'profile')
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      toast.success('已导出 ingestion policy')
    } catch (err: any) {
      toast.error(formatApiError(err, '导出 ingestion policy 失败'))
    }
  }

  const deleteOne = async (p: GovernanceProfileSummary) => {
    if (p.is_system) return
    const ref = String(p.id || '').trim() || p.key
    if (!ref) return
    try {
      await pipelineApi.deleteGovernanceProfile(ref)
      toast.success('已删除')
      detachPromise(load())
    } catch (err: any) {
      toast.error(formatApiError(err, '删除失败'))
    }
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <ProfileEditorDrawer
        open={editorOpen}
        mode={editorMode}
        profileRef={editorProfileRef}
        seedCreate={editorSeedCreate}
        onOpenChange={(next) => {
          setEditorOpen(next)
          if (!next) setEditorSeedCreate(null)
        }}
        onSaved={() => detachPromise(load())}
        onCreated={() => detachPromise(load())}
      />
      <PageScaffold
        title="治理 Profiles"
        description="创建/管理治理配置（清洗规则与 pipeline_patch），用于入库前的数据治理阶段。"
        icon={ShieldCheck}
        iconColor="text-emerald-600 dark:text-emerald-400"
        size="7xl"
        actions={
          <div className="flex items-center gap-2">
            <input
              ref={importInputRef}
              type="file"
              accept="application/json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (!file) return
                detachPromise((async () => {
                  setImporting(true)
                  try {
                    const result = await pipelineApi.importGovernanceProfiles(file, importOverwrite)
                    toast.success(`导入完成：created=${result.created}, updated=${result.updated}`)
                    detachPromise(load())
                  } catch (err: any) {
                    toast.error(formatApiError(err, '导入失败'))
                  } finally {
                    setImporting(false)
                    if (importInputRef.current) importInputRef.current.value = ''
                  }
                })())
              }}
            />
            <Button
              size="sm"
              className="gap-2 rounded-xl"
              onClick={() => {
                setEditorMode('create')
                setEditorProfileRef(null)
                setEditorSeedCreate(null)
                setEditorOpen(true)
              }}
            >
              <Plus className="w-4 h-4" />
              新建
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="gap-2 rounded-xl"
              disabled={importing}
              onClick={() => importInputRef.current?.click()}
            >
              <Upload className={cn('w-4 h-4', importing && 'animate-pulse')} />
              导入
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="gap-2 rounded-xl"
              disabled={loading}
              onClick={() => detachPromise(load())}
            >
              <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
          </div>
        }
      >
        <Panel className="mt-4" padding="lg">
          <div className="flex flex-col md:flex-row md:items-center gap-3">
            <Input
              placeholder="搜索 name/description/key"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <Button
              type="button"
              variant={includeBuiltin ? 'default' : 'outline'}
              className="rounded-xl"
              onClick={() => setIncludeBuiltin((v) => !v)}
            >
              {includeBuiltin ? '包含内置' : '仅自定义'}
            </Button>
            <Button
              type="button"
              variant={importOverwrite ? 'default' : 'outline'}
              className="rounded-xl"
              onClick={() => setImportOverwrite((v) => !v)}
            >
              {importOverwrite ? '导入覆盖: ON' : '导入覆盖: OFF'}
            </Button>
          </div>
        </Panel>

        {items.length ? (
          <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
            {items.map((p) => (
              <Panel key={p.key} padding="lg" className="rounded-2xl">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <div className="font-semibold text-foreground truncate">{p.name}</div>
                      {p.is_system ? (
                        <span className="px-2 py-0.5 rounded-full text-[11px] border border-border bg-muted/40 text-muted-foreground">
                          built-in
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full text-[11px] border border-border bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
                          custom
                        </span>
                      )}
                    </div>
                    <div className="mt-2 text-[12px] text-muted-foreground font-mono break-all">{p.key}</div>
                    {p.description ? (
                      <div className="mt-2 text-sm text-muted-foreground line-clamp-3">{p.description}</div>
                    ) : null}
                  </div>

                  <div className="flex items-center gap-2 flex-shrink-0">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="rounded-xl"
                      onClick={() => {
                        setEditorMode(p.is_system ? 'view' : 'edit')
                        // IMPORTANT: custom profiles should use `id` (UUID) as ref; `key` may be "custom:<uuid>".
                        const ref = p.is_system ? p.key : String(p.id || '').trim() || p.key
                        setEditorSeedCreate(null)
                        setEditorProfileRef(ref)
                        setEditorOpen(true)
                      }}
                    >
                      {p.is_system ? '查看' : '编辑'}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="rounded-xl"
                      aria-label="复制 Profile"
                      onClick={() =>
                        detachPromise((async () => {
                          const ref = p.is_system ? p.key : String(p.id || '').trim() || p.key
                          if (!ref) return
                          try {
                            const prof = await pipelineApi.getGovernanceProfile(ref)
                            setEditorMode('create')
                            setEditorProfileRef(null)
                            setEditorSeedCreate(buildGovernanceProfileCreateFromExisting(prof))
                            setEditorOpen(true)
                          } catch (err: any) {
                            toast.error(formatApiError(err, '复制失败'))
                          }
                        })())
                      }
                    >
                      <Copy className="w-4 h-4" />
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="rounded-xl"
                      aria-label="导出 Profile JSON"
                      onClick={() => detachPromise(exportOne(p))}
                    >
                      <Download className="w-4 h-4" />
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="rounded-xl"
                      aria-label="导出为 ingestion policy"
                      onClick={() => detachPromise(exportAsIngestionPolicy(p))}
                    >
                      <Download className="w-4 h-4" />
                    </Button>
                    <ConfirmDialog
                      title="删除该 Profile？"
                      description={
                        <>
                          此操作不可恢复：
                          <div className="mt-2 rounded-lg border border-border bg-muted/20 px-3 py-2">
                            <div className="text-xs font-semibold text-foreground truncate">{p.name || p.key}</div>
                            <div className="mt-0.5 text-[10px] font-mono text-muted-foreground truncate">{p.key}</div>
                          </div>
                        </>
                      }
                      confirmLabel="删除"
                      cancelLabel="返回"
                      confirmVariant="destructive"
                      confirmDisabled={p.is_system}
                      onConfirm={() => detachPromise(deleteOne(p))}
                    >
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="rounded-xl text-destructive hover:text-destructive"
                        disabled={p.is_system}
                        aria-label="删除 Profile"
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </ConfirmDialog>
                  </div>
                </div>
              </Panel>
            ))}
          </div>
        ) : (
          <EmptyState
            className="mt-6"
            title={loading ? '正在加载…' : '暂无 Profiles'}
            description={
              loading ? '请稍候' : '你可以创建一个自定义 Profile，或切换“包含内置”查看内置预设。'
            }
            icon={ShieldCheck}
          />
        )}
      </PageScaffold>
    </div>
  )
}
