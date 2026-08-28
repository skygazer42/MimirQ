'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useRef, useState } from 'react'
import {
  Copy,
  Download,
  Eye,
  Hash,
  Layers,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react'
import { toast } from 'sonner'
import { Link } from '@/i18n/navigation'

import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { EmptyState } from '@/components/ui/empty-state'
import { Switch } from '@/components/ui/switch'
import {
  KnowledgeOpsFlowCard,
  KnowledgeOpsHero,
  KNOWLEDGE_OPS_SUMMARY_PANEL_CLASS,
} from '@/components/ui/knowledge-ops-hero'
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
import { queryKeys } from '@/lib/query-keys'
import type {
  GovernanceProfileCreate,
  GovernanceProfileSummary,
} from '@/types'
import { ProfileEditorDrawer } from '@/components/governance-profiles/profile-editor-drawer'
import {
  buildGovernanceProfileCreateFromExisting,
  buildIngestionPolicyExportFilename,
} from '@/lib/governance-profile-utils'

export function GovernanceProfilesPage() {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [includeBuiltin, setIncludeBuiltin] = useState(true)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editorMode, setEditorMode] = useState<'create' | 'edit' | 'view'>(
    'create'
  )
  const [editorProfileRef, setEditorProfileRef] = useState<string | null>(null)
  const [editorSeedCreate, setEditorSeedCreate] =
    useState<GovernanceProfileCreate | null>(null)
  const [deleteTarget, setDeleteTarget] =
    useState<GovernanceProfileSummary | null>(null)
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

  const profilesQuery = useQuery({
    queryKey: queryKeys.governance.profiles(params),
    queryFn: () => pipelineApi.listGovernanceProfiles(params),
  })
  const resp = profilesQuery.data ?? null
  const loading = profilesQuery.isFetching
  const profileLoadError = profilesQuery.error
    ? formatApiError(profilesQuery.error, '加载治理 Profiles 失败')
    : null

  const invalidateProfiles = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.governance.profiles(params),
    })
  }

  const importProfilesMutation = useMutation({
    mutationFn: (file: File) =>
      pipelineApi.importGovernanceProfiles(file, importOverwrite),
    onSuccess: (result) => {
      toast.success(`导入完成：created=${result.created}, updated=${result.updated}`)
      invalidateProfiles()
    },
    onError: (err) => {
      toast.error(formatApiError(err, '导入失败'))
    },
    onSettled: () => {
      if (importInputRef.current) importInputRef.current.value = ''
    },
  })

  const deleteProfileMutation = useMutation({
    mutationFn: async (p: GovernanceProfileSummary) => {
      if (p.is_system) return
      const ref = String(p.id || '').trim() || p.key
      if (!ref) return
      await pipelineApi.deleteGovernanceProfile(ref)
    },
    onSuccess: () => {
      toast.success('已删除')
      invalidateProfiles()
    },
    onError: (err) => {
      toast.error(formatApiError(err, '删除失败'))
    },
  })

  const items = useMemo<GovernanceProfileSummary[]>(
    () => resp?.items || [],
    [resp?.items]
  )
  const builtinCount = useMemo(
    () => items.filter((item) => item.is_system).length,
    [items]
  )
  const customCount = useMemo(
    () => items.length - builtinCount,
    [items, builtinCount]
  )

  const exportOne = async (p: GovernanceProfileSummary) => {
    const ref = p.is_system ? p.key : String(p.id || '').trim() || p.key
    if (!ref) return
    try {
      const blob = await pipelineApi.exportGovernanceProfile(ref)
      const safe = (p.key || 'profile')
        .replaceAll(/[\\/:*?"<>|]+/g, '_')
        .slice(0, 120)
      const filename = `${safe}.governance-profile.json`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      toast.success('已导出')
    } catch (err: unknown) {
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
    } catch (err: unknown) {
      toast.error(formatApiError(err, '导出 ingestion policy 失败'))
    }
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-background">
      <AlertDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除该治理配置？</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div>
                此操作不可恢复。
                {deleteTarget ? (
                  <div className="mt-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2">
                    <div className="truncate text-sm font-medium text-foreground/85">
                      {deleteTarget.name || deleteTarget.key}
                    </div>
                    <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                      {deleteTarget.key}
                    </div>
                  </div>
                ) : null}
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setDeleteTarget(null)}>
              返回
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (!deleteTarget) return
                deleteProfileMutation.mutate(deleteTarget)
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
        onSaved={invalidateProfiles}
        onCreated={invalidateProfiles}
      />
      <PageScaffold
        title="治理配置"
        iconImage="governance-config"
        description="创建和管理可复用的治理模板，用于清洗规则与 pipeline_patch 编排。"
        icon={ShieldCheck}
        iconColor="text-info"
        size="7xl"
        showHeader={false}
        topClassName="relative z-10 w-full max-w-none px-4 md:px-6 pt-3 md:pt-4 pb-2 md:pb-3"
        top={
          <KnowledgeOpsHero
            iconImage="governance-config"
            title="治理配置"
            description="创建和管理可复用的治理模板，用于清洗规则与 pipeline_patch 编排。"
            summary={
              <div className="grid gap-2 sm:grid-cols-2">
                <div className={KNOWLEDGE_OPS_SUMMARY_PANEL_CLASS}>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="size-1 rounded-full bg-info/70" aria-hidden />
                    配置
                  </span>
                  <span className="font-mono tabular-nums text-foreground">
                    {items.length}
                  </span>
                  <span className="h-3.5 w-px bg-border/70" />
                  <span>自定义</span>
                  <span className="font-mono tabular-nums text-foreground">
                    {customCount}
                  </span>
                </div>
                <KnowledgeOpsFlowCard
                  steps={[
                    { icon: Upload, label: '导入' },
                    { icon: Layers, label: '编排' },
                    { icon: ShieldCheck, label: '复用' },
                  ]}
                />
              </div>
            }
            actions={
              <>
                <input
                  ref={importInputRef}
                  type="file"
                  accept="application/json"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (!file) return
                    importProfilesMutation.mutate(file)
                  }}
                />
                <Button
                  asChild
                  size="sm"
                  variant="outline"
                  className="h-9 gap-2 rounded-xl border-border/60 bg-card px-4 text-[12px] font-semibold shadow-subtle"
                >
                  <Link href="/data-governance/common-lines">
                    <Hash className="w-3.5 h-3.5" />
                    重复内容治理
                  </Link>
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-9 gap-2 rounded-xl border-border/60 bg-card px-4 text-[12px] font-semibold shadow-subtle"
                  disabled={loading}
                  onClick={() => {
                    profilesQuery.refetch()
                  }}
                >
                  <RefreshCw
                    className={cn(
                      'w-3.5 h-3.5',
                      loading && 'animate-spin motion-reduce:animate-none'
                    )}
                  />
                  刷新
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-9 gap-2 rounded-xl border-border/60 bg-card px-4 text-[12px] font-semibold shadow-subtle"
                  disabled={importProfilesMutation.isPending}
                  onClick={() => importInputRef.current?.click()}
                >
                  <Upload
                    className={cn(
                      'w-3.5 h-3.5',
                      importProfilesMutation.isPending && 'animate-pulse'
                    )}
                  />
                  导入
                </Button>
                <Button
                  size="sm"
                  className="h-9 gap-2 rounded-xl border-info/25 bg-info/[0.06] px-4 text-[12px] font-semibold text-info shadow-[0_12px_24px_-22px_hsl(var(--info)/0.5)] hover:border-info/40 hover:bg-info/[0.12] hover:text-info"
                  onClick={() => {
                    setEditorMode('create')
                    setEditorProfileRef(null)
                    setEditorSeedCreate(null)
                    setEditorOpen(true)
                  }}
                >
                  <Plus className="w-3.5 h-3.5" />
                  新建
                </Button>
              </>
            }
          />
        }
        >
          {profileLoadError ? (
            <Panel className="mt-4 border-destructive/30 bg-destructive/10 text-destructive" padding="md">
              {profileLoadError}
            </Panel>
          ) : null}

        <Panel
          className="mt-4 overflow-hidden rounded-2xl border-border/50 bg-background shadow-none"
          padding="md"
        >
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <div className="relative overflow-hidden rounded-xl border border-border/50 from-muted/40 via-muted/15 to-transparent px-3 py-2.5">
              <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground/75">
                <Layers className="size-3 text-muted-foreground/60" />
                总数
              </div>
              <div className="mt-1.5 flex items-baseline gap-1.5">
                <span className="text-[20px] font-semibold tracking-[-0.02em] tabular-nums text-foreground">
                  {items.length}
                </span>
                <span className="text-[11px] text-muted-foreground/65">
                  profiles
                </span>
              </div>
            </div>
            <div className="relative overflow-hidden rounded-xl border border-info/20 from-info/[0.10] via-info/[0.04] to-transparent px-3 py-2.5">
              <span
                aria-hidden
                className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full bg-info/70"
              />
              <div className="flex items-center gap-2 pl-1.5 text-[11px] font-medium uppercase tracking-[0.14em] text-info/85">
                <ShieldCheck className="size-3 text-info" />
                内置
              </div>
              <div className="mt-1.5 flex items-baseline gap-1.5 pl-1.5">
                <span className="text-[20px] font-semibold tracking-[-0.02em] tabular-nums text-foreground">
                  {builtinCount}
                </span>
                <span className="text-[11px] text-muted-foreground/65">
                  系统基线
                </span>
              </div>
            </div>
            <div className="relative overflow-hidden rounded-xl border border-accent/20 from-accent/[0.08] via-accent/[0.03] to-transparent px-3 py-2.5">
              <span
                aria-hidden
                className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full bg-accent/70"
              />
              <div className="flex items-center gap-2 pl-1.5 text-[11px] font-medium uppercase tracking-[0.14em] text-accent/85">
                <Sparkles className="size-3 text-accent" />
                自定义
              </div>
              <div className="mt-1.5 flex items-baseline gap-1.5 pl-1.5">
                <span className="text-[20px] font-semibold tracking-[-0.02em] tabular-nums text-foreground">
                  {customCount}
                </span>
                <span className="text-[11px] text-muted-foreground/65">
                  团队沉淀
                </span>
              </div>
            </div>
          </div>
        </Panel>

        <Panel
          className="mt-3 border-border/50 bg-background shadow-none"
          padding="md"
        >
          <div className="flex flex-col gap-2 md:flex-row md:items-center">
            <div className="relative md:flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground/60" />
              <Input
                placeholder="搜索名称、说明或 key"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="h-9 border-border/60 bg-background pl-9 text-[13px] shadow-none transition-colors hover:border-info/30 focus-visible:border-info/50 focus-visible:ring-2 focus-visible:ring-info/15"
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label
                className={cn(
                  'inline-flex h-9 cursor-pointer items-center gap-2 rounded-lg border px-3 text-[12px] font-medium transition-colors duration-150 motion-reduce:transition-none',
                  includeBuiltin
                    ? 'border-info/30 bg-info/[0.08] text-info'
                    : 'border-border/60 bg-muted/40 text-muted-foreground hover:bg-muted/60 hover:text-foreground'
                )}
              >
                <Switch
                  checked={includeBuiltin}
                  onCheckedChange={setIncludeBuiltin}
                  className="scale-90"
                />
                <span>包含内置</span>
              </label>
              <label
                className={cn(
                  'inline-flex h-9 cursor-pointer items-center gap-2 rounded-lg border px-3 text-[12px] font-medium transition-colors duration-150 motion-reduce:transition-none',
                  importOverwrite
                    ? 'border-warning/35 bg-warning/[0.10] text-warning'
                    : 'border-border/60 bg-muted/40 text-muted-foreground hover:bg-muted/60 hover:text-foreground'
                )}
                title="导入时覆盖同名 Profile"
              >
                <Switch
                  checked={importOverwrite}
                  onCheckedChange={setImportOverwrite}
                  className="scale-90"
                />
                <span>导入覆盖</span>
              </label>
            </div>
          </div>
        </Panel>

        {items.length ? (
          <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
            {items.map((p) => {
              const tone = p.is_system ? 'info' : 'accent'
              const toneRailClass =
                tone === 'info' ? 'bg-info/70' : 'bg-accent/70'
              const toneGradientClass =
                tone === 'info'
                  ? 'from-info/[0.06] via-info/[0.02] to-transparent dark:from-info/[0.10]'
                  : 'from-accent/[0.05] via-accent/[0.015] to-transparent dark:from-accent/[0.10]'
              const toneHoverBorderClass =
                tone === 'info'
                  ? 'hover:border-info/40'
                  : 'hover:border-accent/40'
              const toneBadgeClass =
                tone === 'info'
                  ? 'border-info/30 bg-info/[0.12] text-info'
                  : 'border-accent/30 bg-accent/[0.12] text-accent'
              const toneDotClass = tone === 'info' ? 'bg-info' : 'bg-accent'
              return (
                <Panel
                  key={p.key}
                  padding="md"
                  className={cn(
                    'group relative overflow-hidden rounded-2xl border-border/60 bg-background shadow-none transition-[border-color,box-shadow,transform] duration-200 motion-reduce:transition-none',
                    toneHoverBorderClass,
                    'hover:shadow-soft'
                  )}
                >
                  <span
                    aria-hidden
                    className={cn(
                      'absolute left-0 top-3 bottom-3 w-[2px] rounded-full',
                      toneRailClass
                    )}
                  />
                  <div
                    className={cn(
                      'pointer-events-none absolute inset-0 opacity-80',
                      toneGradientClass
                    )}
                    aria-hidden
                  />

                  <div className="relative flex items-start justify-between gap-2.5">
                    <div className="min-w-0 flex-1 pl-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <div
                          title={p.name}
                          className="min-w-0 flex-1 truncate text-[14px] font-semibold tracking-[-0.005em] text-foreground"
                        >
                          {p.name}
                        </div>
                        <span
                          className={cn(
                            'flex-shrink-0 whitespace-nowrap rounded-full border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.10em]',
                            toneBadgeClass
                          )}
                        >
                          {p.is_system ? '内置' : '自定义'}
                        </span>
                      </div>
                      <div className="mt-1.5 inline-flex max-w-full items-center rounded-md border border-border/50 bg-muted/40 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                        <span className="truncate">{p.key}</span>
                      </div>
                      <div className="mt-2 min-h-[2.6rem] text-[12px] leading-5 text-muted-foreground/85 line-clamp-3">
                        {p.description ||
                          (p.is_system
                            ? '适合作为治理基线模板，可直接查看并克隆为团队自定义配置。'
                            : '用于沉淀团队治理经验，可继续编辑、导出或用于入库策略复用。')}
                      </div>
                    </div>

                    <div className="flex flex-shrink-0 items-center gap-1">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 gap-1 rounded-md px-2 text-[12px] font-medium"
                        onClick={() => {
                          setEditorMode(p.is_system ? 'view' : 'edit')
                          // IMPORTANT: custom profiles should use `id` (UUID) as ref; `key` may be"custom:<uuid>".
                          const ref = p.is_system
                            ? p.key
                            : String(p.id || '').trim() || p.key
                          setEditorSeedCreate(null)
                          setEditorProfileRef(ref)
                          setEditorOpen(true)
                        }}
                      >
                        <Eye className="h-3.5 w-3.5" />
                        {p.is_system ? '查看' : '编辑'}
                      </Button>
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60"
                        aria-label="复制 Profile"
                        title="复制"
                        onClick={() =>
                          detachPromise(
                            (async () => {
                              const ref = p.is_system
                                ? p.key
                                : String(p.id || '').trim() || p.key
                              if (!ref) return
                              try {
                                const prof =
                                  await pipelineApi.getGovernanceProfile(ref)
                                setEditorMode('create')
                                setEditorProfileRef(null)
                                setEditorSeedCreate(
                                  buildGovernanceProfileCreateFromExisting(prof)
                                )
                                setEditorOpen(true)
                              } catch (err: unknown) {
                                toast.error(formatApiError(err, '复制失败'))
                              }
                            })()
                          )
                        }
                      >
                        <Copy className="h-3.5 w-3.5" />
                      </Button>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            size="icon"
                            variant="ghost"
                            className="h-7 w-7 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/60"
                            aria-label="更多操作"
                            title="更多操作"
                          >
                            <MoreHorizontal className="h-3.5 w-3.5" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-48">
                          <DropdownMenuItem
                            onSelect={() => detachPromise(exportOne(p))}
                          >
                            <Download className="mr-2 h-4 w-4" />
                            导出配置 JSON
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() =>
                              detachPromise(exportAsIngestionPolicy(p))
                            }
                          >
                            <Download className="mr-2 h-4 w-4" />
                            导出入库策略
                          </DropdownMenuItem>
                          {p.is_system ? null : (
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
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </div>

                  <div className="relative mt-3 flex items-center justify-between border-t border-border/50 pt-2.5 pl-2">
                    <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground/85">
                      <span
                        aria-hidden
                        className={cn('size-1.5 rounded-full', toneDotClass)}
                      />
                      <span>
                        {p.is_system ? '系统基线模板' : '团队自定义模板'}
                      </span>
                    </div>
                    <div className="text-[11px] text-muted-foreground/70">
                      {p.is_system ? '支持克隆' : '支持编辑与导出'}
                    </div>
                  </div>
                </Panel>
              )
            })}
          </div>
        ) : (
          <EmptyState
            className="mt-6 border-border/60 bg-background"
            title={loading ? '正在加载…' : '暂无 Profiles'}
            description={
              loading
                ? '请稍候'
                : '你可以创建一个自定义 Profile，或切换"包含内置"查看内置预设。'
            }
            icon={ShieldCheck}
          >
            {loading ? null : (
              <Button
                size="sm"
                className="bg-info text-info-foreground hover:bg-info/90 dark:bg-info/85 dark:hover:bg-info"
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
            )}
          </EmptyState>
        )}
      </PageScaffold>
    </div>
  )
}
