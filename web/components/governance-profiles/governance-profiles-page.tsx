'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Copy, Download, Eye, MoreHorizontal, Plus, RefreshCw, ShieldCheck, Trash2, Upload } from 'lucide-react'
import { toast } from 'sonner'

import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { EmptyState } from '@/components/ui/empty-state'
import { Switch } from '@/components/ui/switch'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { pipelineApi } from '@/lib/api'
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
  const [deleteTarget, setDeleteTarget] = useState<GovernanceProfileSummary | null>(null)
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

  const items = useMemo<GovernanceProfileSummary[]>(() => resp?.items || [], [resp?.items])
  const builtinCount = useMemo(() => items.filter((item) => item.is_system).length, [items])
  const customCount = useMemo(() => items.length - builtinCount, [items, builtinCount])

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
      <AlertDialog open={Boolean(deleteTarget)} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除该治理配置？</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div>
                此操作不可恢复。
                {deleteTarget ? (
                  <div className="mt-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2">
                    <div className="truncate text-sm font-medium text-foreground/85">{deleteTarget.name || deleteTarget.key}</div>
                    <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{deleteTarget.key}</div>
                  </div>
                ) : null}
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setDeleteTarget(null)}>返回</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (!deleteTarget) return
                detachPromise(deleteOne(deleteTarget))
                setDeleteTarget(null)
              }}
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

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
        title="治理配置"
        description={
          <span data-governance-profiles-subtitle>
            创建和管理可复用的治理模板，用于清洗规则与 pipeline_patch 编排。
          </span>
        }
        icon={ShieldCheck}
        iconColor="text-emerald-600 dark:text-emerald-400"
        size="7xl"
        headerClassName="[&_h1]:font-medium [&_h1]:tracking-[-0.015em] [&_h1]:text-foreground/78 [&_[data-governance-profiles-subtitle]]:text-[13px] [&_[data-governance-profiles-subtitle]]:leading-5 [&_[data-governance-profiles-subtitle]]:text-muted-foreground/78"
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
              variant="outline"
              className="h-8 gap-1.5 rounded-xl border-border/55 bg-background/78 px-3 text-[12px] font-medium text-foreground/74 shadow-none hover:bg-muted/[0.18] hover:text-foreground"
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
              className="h-8 gap-1.5 rounded-xl border-border/50 bg-background/74 px-3 text-[12px] font-medium text-foreground/68 shadow-none hover:bg-muted/[0.18] hover:text-foreground/78"
              disabled={importing}
              onClick={() => importInputRef.current?.click()}
            >
              <Upload className={cn('w-4 h-4', importing && 'animate-pulse')} />
              导入
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1.5 rounded-xl border-border/50 bg-background/74 px-3 text-[12px] font-medium text-foreground/68 shadow-none hover:bg-muted/[0.18] hover:text-foreground/78"
              disabled={loading}
              onClick={() => detachPromise(load())}
            >
              <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
          </div>
        }
      >
        <Panel
          className="mt-4 overflow-hidden rounded-2xl border-border/40 bg-[linear-gradient(180deg,rgba(255,255,255,0.94)_0%,rgba(248,250,252,0.92)_100%)] shadow-none hover:shadow-none"
          padding="md"
        >
          <div className="flex flex-col gap-1.5 lg:flex-row lg:items-center">
            <div className="min-w-0 rounded-xl border border-border/35 bg-background/78 px-3 py-2">
              <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground/75">
                Profile Library
              </div>
              <div className="mt-0.5 text-[11px] leading-4.5 text-foreground/72">
                内置模板用于建立治理基线，自定义模板适合沉淀团队场景规则，并可继续克隆、导出或编辑。
              </div>
            </div>
            <div className="grid flex-1 gap-1.5 sm:grid-cols-3">
              <div className="rounded-xl border border-border/30 bg-background/72 px-3 py-2">
                <div className="flex items-end justify-between gap-3">
                  <div className="text-[11px] text-muted-foreground/75">当前展示</div>
                  <div className="text-[16px] font-semibold tracking-[-0.02em] leading-none text-foreground/80">{items.length}</div>
                </div>
              </div>
              <div className="rounded-xl border border-border/30 bg-background/72 px-3 py-2">
                <div className="flex items-end justify-between gap-3">
                  <div className="text-[11px] text-muted-foreground/75">内置模板</div>
                  <div className="text-[16px] font-semibold tracking-[-0.02em] leading-none text-foreground/80">{builtinCount}</div>
                </div>
              </div>
              <div className="rounded-xl border border-border/30 bg-background/72 px-3 py-2">
                <div className="flex items-end justify-between gap-3">
                  <div className="text-[11px] text-muted-foreground/75">自定义模板</div>
                  <div className="text-[16px] font-semibold tracking-[-0.02em] leading-none text-foreground/80">{customCount}</div>
                </div>
              </div>
            </div>
          </div>
        </Panel>

        <Panel className="mt-4 border-border/38 bg-card/90 shadow-none hover:shadow-none" padding="md">
          <div className="flex flex-col gap-2.5 md:flex-row md:items-center">
            <Input
              placeholder="搜索名称、说明或 key"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="h-9 border-border/45 bg-background/80 text-[13px] shadow-none transition-colors focus-visible:border-border/70 focus-visible:ring-[rgba(148,163,184,0.14)] md:flex-1"
            />
            <div className="flex flex-wrap items-center gap-2">
              <label
                className={cn(
                  "inline-flex h-9 items-center gap-2 rounded-xl px-3 text-[12px] text-foreground/70 transition-colors",
                  includeBuiltin
                    ? "border border-border/55 bg-background/84 hover:bg-muted/[0.18]"
                    : "border border-border/35 bg-background/68 hover:bg-muted/[0.14]"
                )}
              >
                <Switch checked={includeBuiltin} onCheckedChange={setIncludeBuiltin} className="scale-90" />
                <span>包含内置</span>
              </label>
              <label
                className={cn(
                  "inline-flex h-9 items-center gap-2 rounded-xl px-3 text-[12px] text-foreground/70 transition-colors",
                  importOverwrite
                    ? "border border-border/55 bg-background/84 hover:bg-muted/[0.18]"
                    : "border border-border/35 bg-background/68 hover:bg-muted/[0.14]"
                )}
              >
                <Switch checked={importOverwrite} onCheckedChange={setImportOverwrite} className="scale-90" />
                <span>导入覆盖</span>
              </label>
            </div>
          </div>
        </Panel>

        {items.length ? (
          <div className="mt-4 grid grid-cols-1 gap-3.5 lg:grid-cols-2">
            {items.map((p) => (
              <Panel
                key={p.key}
                padding="md"
                className={cn(
                  "group relative overflow-hidden rounded-2xl shadow-none transition-[border-color,background-color] duration-200 hover:shadow-none",
                  p.is_system
                    ? "border-[#aad9f2]/38 bg-[rgba(255,255,255,0.86)] hover:border-[#aad9f2]/72 hover:bg-[rgba(209,255,255,0.20)] before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-[linear-gradient(90deg,transparent,rgba(170,217,242,0.55),transparent)]"
                    : "border-[#aad9f2]/34 bg-[rgba(255,255,255,0.88)] hover:border-[#aad9f2]/66 hover:bg-[linear-gradient(180deg,rgba(226,255,212,0.22)_0%,rgba(209,255,255,0.14)_100%)] before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-[linear-gradient(90deg,transparent,rgba(226,255,212,1),transparent)]"
                )}
              >
                <div
                  aria-hidden="true"
                  className={cn(
                    "pointer-events-none absolute right-0 top-0 h-24 w-24 rounded-full blur-2xl opacity-70 transition-all duration-200 group-hover:opacity-100",
                    p.is_system ? "bg-[#d1ffff]/55 group-hover:bg-[#aad9f2]/45" : "bg-[#e2ffd4]/55 group-hover:bg-[#d1ffff]/45"
                  )}
                />
                <div
                  aria-hidden="true"
                  className={cn(
                    "pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-200 group-hover:opacity-100",
                    p.is_system
                      ? "bg-[radial-gradient(circle_at_top_right,rgba(209,255,255,0.34),transparent_62%)]"
                      : "bg-[radial-gradient(circle_at_top_right,rgba(226,255,212,0.34),rgba(209,255,255,0.18),transparent_66%)]"
                  )}
                />
                <div className="flex items-start justify-between gap-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <div title={p.name} className="min-w-0 flex-1 truncate text-[14px] font-semibold tracking-[-0.01em] text-foreground/82">
                        {p.name}
                      </div>
                      {p.is_system ? (
                        <span className="flex-shrink-0 whitespace-nowrap rounded-full border border-[#aad9f2]/50 bg-[rgba(209,255,255,0.32)] px-2 py-0.5 text-[9px] font-medium tracking-[0.08em] text-slate-600/85">
                          内置
                        </span>
                      ) : (
                        <span className="flex-shrink-0 whitespace-nowrap rounded-full border border-[#aad9f2]/35 bg-[rgba(226,255,212,0.42)] px-2 py-0.5 text-[9px] font-medium tracking-[0.08em] text-emerald-700/85 dark:text-emerald-300/85">
                          自定义
                        </span>
                      )}
                    </div>
                    <div className="mt-1.5 inline-flex max-w-full items-center rounded-md border border-border/45 bg-muted/[0.14] px-2 py-0.5 font-mono text-[11px] text-muted-foreground/85 transition-colors duration-200 group-hover:border-[#aad9f2]/50 group-hover:bg-[rgba(209,255,255,0.26)]">
                      <span className="truncate">{p.key}</span>
                    </div>
                    <div className="mt-1.5 min-h-[2.8rem] text-[12px] leading-5 text-muted-foreground/84 line-clamp-3">
                      {p.description || (p.is_system ? '适合作为治理基线模板，可直接查看并克隆为团队自定义配置。' : '用于沉淀团队治理经验，可继续编辑、导出或用于入库策略复用。')}
                    </div>
                  </div>

                  <div className="flex flex-shrink-0 items-center gap-1.5">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className={cn(
                        "h-[30px] gap-1 rounded-lg px-2.5 text-[12px] text-foreground/70 shadow-none",
                        p.is_system
                          ? "border-[#aad9f2]/42 bg-[rgba(209,255,255,0.12)] hover:bg-[rgba(209,255,255,0.28)] hover:text-foreground"
                          : "border-[#aad9f2]/38 bg-[rgba(226,255,212,0.16)] hover:bg-[rgba(226,255,212,0.32)] hover:text-foreground"
                      )}
                      onClick={() => {
                        setEditorMode(p.is_system ? 'view' : 'edit')
                        // IMPORTANT: custom profiles should use `id` (UUID) as ref; `key` may be "custom:<uuid>".
                        const ref = p.is_system ? p.key : String(p.id || '').trim() || p.key
                        setEditorSeedCreate(null)
                        setEditorProfileRef(ref)
                        setEditorOpen(true)
                      }}
                    >
                      <Eye className="h-4 w-4" />
                      {p.is_system ? '查看' : '编辑'}
                    </Button>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className={cn(
                        "h-[30px] w-[30px] rounded-lg text-muted-foreground/75 transition-opacity group-hover:opacity-100 md:opacity-80",
                        p.is_system
                          ? "hover:bg-[rgba(209,255,255,0.30)] hover:text-foreground"
                          : "hover:bg-[rgba(226,255,212,0.30)] hover:text-foreground"
                      )}
                      aria-label="复制 Profile"
                      title="复制"
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
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          className={cn(
                            "h-[30px] w-[30px] rounded-lg text-muted-foreground/75 transition-opacity group-hover:opacity-100 md:opacity-80",
                            p.is_system
                              ? "hover:bg-[rgba(209,255,255,0.30)] hover:text-foreground"
                              : "hover:bg-[rgba(226,255,212,0.30)] hover:text-foreground"
                          )}
                          aria-label="更多操作"
                          title="更多操作"
                        >
                          <MoreHorizontal className="w-4 h-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-48">
                        <DropdownMenuItem onSelect={() => detachPromise(exportOne(p))}>
                          <Download className="mr-2 h-4 w-4" />
                          导出配置 JSON
                        </DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => detachPromise(exportAsIngestionPolicy(p))}>
                          <Download className="mr-2 h-4 w-4" />
                          导出入库策略
                        </DropdownMenuItem>
                        {!p.is_system ? (
                          <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              className="text-destructive focus:text-destructive"
                              onSelect={() => setDeleteTarget(p)}
                            >
                              <Trash2 className="mr-2 h-4 w-4" />
                              删除
                            </DropdownMenuItem>
                          </>
                        ) : null}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>

                <div className="mt-3 flex items-center justify-between border-t border-border/40 pt-2.5">
                  <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground/80">
                    <span
                      className={cn(
                        "h-1.5 w-1.5 rounded-full",
                        p.is_system ? "bg-foreground/20" : "bg-emerald-500/45"
                      )}
                      aria-hidden="true"
                    />
                    <span>{p.is_system ? '系统基线模板' : '团队自定义模板'}</span>
                  </div>
                  <div className="text-[11px] text-muted-foreground/70">
                    {p.is_system ? '支持克隆为新模板' : '支持编辑与导出'}
                  </div>
                </div>
              </Panel>
            ))}
          </div>
        ) : (
          <EmptyState
            className="mt-6 border-border/45 bg-[linear-gradient(180deg,hsl(var(--card)/0.86)_0%,hsl(var(--muted)/0.18)_100%)]"
            title={loading ? '正在加载…' : '暂无 Profiles'}
            description={
              loading ? '请稍候' : '你可以创建一个自定义 Profile，或切换“包含内置”查看内置预设。'
            }
            icon={ShieldCheck}
          >
            {!loading ? (
              <Button
                size="sm"
                className="rounded-xl"
                onClick={() => {
                  setEditorMode('create')
                  setEditorProfileRef(null)
                  setEditorSeedCreate(null)
                  setEditorOpen(true)
                }}
              >
                <Plus className="h-4 w-4" />
                新建治理配置
              </Button>
            ) : null}
          </EmptyState>
        )}
      </PageScaffold>
    </div>
  )
}
