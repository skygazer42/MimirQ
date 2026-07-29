'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  ArrowRight,
  ChevronsLeft,
  Database,
  FileSearch,
  FileText,
  Hash,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  Sliders,
  Sparkles,
  Upload,
  UsersRound,
  Wand2,
} from 'lucide-react'

import { useRouter } from '@/i18n/navigation'
import { PageScaffold } from '@/components/ui/page-scaffold'
import {
  KnowledgeOpsFlowCard,
  KnowledgeOpsHero,
  KNOWLEDGE_OPS_SUMMARY_PANEL_CLASS,
} from '@/components/ui/knowledge-ops-hero'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'

import { datasetApi, pipelineApi } from '@/lib/api'
import type { BuiltinProcessingScript } from '@/lib/api/pipeline'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise } from '@/lib/utils'

import type {
  GovernanceCommonLineCandidate,
  GovernanceCommonLinesLearnResponse,
  GovernanceProfileCreate,
  GovernanceProfileSummary,
  GovernanceProcessingScript,
  RegexRuleModel,
} from '@/types'

function escapeRegex(text: string): string {
  return text.replaceAll(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`)
}

function buildLineRegexRule(sample: string): RegexRuleModel | null {
  const raw = String(sample || '').trim()
  if (!raw) return null
  const tokens = raw.split(/\s+/).filter(Boolean)
  if (!tokens.length) return null
  const body = tokens.map(escapeRegex).join(String.raw`\s+`)
  // (?m): line anchors, (?i): case-insensitive to tolerate casing changes from different parsers.
  const pattern = String.raw`(?mi)^\s*${body}\s*$`
  return { pattern, repl: '', flags: 0 }
}

const emptyWorkflowSteps = [
  {
    icon: FileText,
    title: '扫描文档',
    description: '从数据集中抽取解析结果,识别潜在的反复出现的行。',
  },
  {
    icon: UsersRound,
    title: '聚合重复样行',
    description: '跨文档聚合同类样行,计算命中统计与得分。',
  },
  {
    icon: ShieldCheck,
    title: '写入治理配置',
    description: '勾选需要保留的规则,一键写入治理配置。',
  },
]

const DEFAULT_COMMON_LINES_PROFILE_KEY = 'common-lines-default'

const DEFAULT_COMMON_LINES_PROFILE: GovernanceProfileCreate = {
  key: DEFAULT_COMMON_LINES_PROFILE_KEY,
  name: '重复内容治理默认配置',
  description: '用于承接重复内容治理生成的页眉、页脚、导航和免责声明清洗规则。',
  payload: {
    version: '1',
    extends: null,
    input_formats: ['markdown'],
    pipeline_patch: {
      governance_enabled: true,
      governance_remove_toc_lines: true,
      governance_remove_noise_lines: true,
      governance_unwrap_lines: true,
      governance_remove_common_lines: true,
      governance_max_blank_lines: 1,
    },
    regex_rules: [],
  },
}

const SCRIPT_UPLOAD_ACCEPT = '.js,.ts,.py,.rs'
const MAX_PROCESSING_SCRIPT_CHARS = 200_000
const COMMON_LINES_PROFILE_PARAMS = {
  include_builtin: false,
  limit: 200,
} as const

function detectScriptLanguage(
  filename: string
): GovernanceProcessingScript['language'] | null {
  const ext = filename.trim().toLowerCase().split('.').pop()
  if (ext === 'js') return 'javascript'
  if (ext === 'ts') return 'typescript'
  if (ext === 'py') return 'python'
  if (ext === 'rs') return 'rust'
  return null
}

async function listWritableCommonLineProfiles(): Promise<
  GovernanceProfileSummary[]
> {
  const profResp = await pipelineApi.listGovernanceProfiles(
    COMMON_LINES_PROFILE_PARAMS
  )
  let profs = (profResp.items || []).filter((p) => !p.is_system)
  if (!profs.length) {
    try {
      const created = await pipelineApi.createGovernanceProfile(
        DEFAULT_COMMON_LINES_PROFILE
      )
      profs = [created]
    } catch (caughtCreateErr: unknown) {
      const createErr = caughtCreateErr as { response?: { status?: number } }
      if (createErr?.response?.status !== 409) throw caughtCreateErr
      const retryResp = await pipelineApi.listGovernanceProfiles(
        COMMON_LINES_PROFILE_PARAMS
      )
      profs = (retryResp.items || []).filter((p) => !p.is_system)
    }
  }
  return profs
}

export function GovernanceCommonLinesPage() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const uploadInputRef = useRef<HTMLInputElement | null>(null)

  const [datasetId, setDatasetId] = useState<string>('')
  const [profileRef, setProfileRef] = useState<string>('')

  const [limitDocs, setLimitDocs] = useState(20)
  const [useOriginal, setUseOriginal] = useState(true)
  const [minDocs, setMinDocs] = useState(3)
  const [minRatio, setMinRatio] = useState(0.5)
  const [maxLineLength, setMaxLineLength] = useState(120)
  const [maxCandidates, setMaxCandidates] = useState(50)
  const [controlsCollapsed, setControlsCollapsed] = useState(false)

  const [loading, setLoading] = useState(false)
  const [importingScript, setImportingScript] = useState(false)
  const [resp, setResp] = useState<GovernanceCommonLinesLearnResponse | null>(
    null
  )
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [templateLibraryOpen, setTemplateLibraryOpen] = useState(false)
  const [selectedTemplateKeys, setSelectedTemplateKeys] = useState<Set<string>>(
    () => new Set()
  )
  const [templateSearch, setTemplateSearch] = useState('')

  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive({ purpose: 'governance-common-lines' }),
    queryFn: () => datasetApi.listAll(),
  })
  const profilesQuery = useQuery({
    queryKey: queryKeys.governance.profiles(COMMON_LINES_PROFILE_PARAMS),
    queryFn: listWritableCommonLineProfiles,
  })
  const templateLibraryQuery = useQuery({
    queryKey: ['governance-processing-scripts', 'builtins'] as const,
    queryFn: () => pipelineApi.listBuiltinProcessingScripts(),
    staleTime: 30 * 60 * 1000,
  })

  const datasets = useMemo(
    () => datasetsQuery.data || [],
    [datasetsQuery.data]
  )
  const profiles = useMemo(
    () => profilesQuery.data || [],
    [profilesQuery.data]
  )
  const loadingMeta = datasetsQuery.isFetching || profilesQuery.isFetching
  const metaError = datasetsQuery.error || profilesQuery.error

  const refreshMeta = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.datasets.exhaustive({ purpose: 'governance-common-lines' }),
    })
    queryClient.invalidateQueries({
      queryKey: queryKeys.governance.profiles(COMMON_LINES_PROFILE_PARAMS),
    })
  }, [queryClient])

  useEffect(() => {
    if (metaError) {
      toast.error(formatApiError(metaError, '加载数据集或治理配置失败'))
    }
  }, [metaError])

  useEffect(() => {
    if (!datasetId && datasets.length) setDatasetId(String(datasets[0].id || ''))
  }, [datasetId, datasets])

  useEffect(() => {
    const profileStillExists = profiles.some((p) => {
      const id = String(p.id || '').trim()
      return profileRef === p.key || (!!id && profileRef === id)
    })
    if ((!profileRef || !profileStillExists) && profiles.length)
      setProfileRef(String(profiles[0].id || profiles[0].key || ''))
  }, [profileRef, profiles])

  const candidates: GovernanceCommonLineCandidate[] = useMemo(
    () => resp?.candidates || [],
    [resp?.candidates]
  )
  const sortedCandidates = useMemo(
    () =>
      [...candidates].sort((a, b) => {
        const docsDelta = Number(b.docs || 0) - Number(a.docs || 0)
        if (docsDelta !== 0) return docsDelta
        return Number(b.ratio || 0) - Number(a.ratio || 0)
      }),
    [candidates]
  )
  const selectedCandidates = useMemo(
    () => candidates.filter((c) => selected[String(c.signature || '')]),
    [candidates, selected]
  )

  const toggleAll = useCallback(
    (on: boolean) => {
      const next: Record<string, boolean> = {}
      for (const c of candidates) {
        const sig = String(c.signature || '')
        if (!sig) continue
        next[sig] = on
      }
      setSelected(next)
    },
    [candidates]
  )

  const runLearn = useCallback(async () => {
    const dsId = datasetId.trim()
    if (!dsId) {
      toast.error('请先选择数据集')
      return
    }
    setLoading(true)
    setResp(null)
    setSelected({})
    try {
      const out = await pipelineApi.learnCommonLines({
        dataset_id: dsId,
        limit_docs: Math.max(2, Math.min(50, Number(limitDocs || 20))),
        use_original: Boolean(useOriginal),
        min_docs: Math.max(2, Math.min(50, Number(minDocs || 3))),
        min_ratio: Math.max(0, Math.min(1, Number(minRatio || 0.5))),
        max_line_length: Math.max(
          20,
          Math.min(400, Number(maxLineLength || 120))
        ),
        max_candidates: Math.max(1, Math.min(200, Number(maxCandidates || 50))),
      })
      setResp(out)
      toast.success(`已生成候选行：${(out.candidates || []).length}`)
    } catch (err: unknown) {
      toast.error(formatApiError(err, '扫描重复行失败'))
    } finally {
      setLoading(false)
    }
  }, [
    datasetId,
    limitDocs,
    maxCandidates,
    maxLineLength,
    minDocs,
    minRatio,
    useOriginal,
  ])

  const importProcessingScripts = useCallback(
    async (files: File[]) => {
      const ref = profileRef.trim()
      if (!ref) {
        toast.error('请先选择写入目标治理配置')
        return
      }
      if (!files.length) return

      setImportingScript(true)
      try {
        const prof = await pipelineApi.getGovernanceProfile(ref)
        if (prof.is_system) {
          toast.error('内置治理配置只读，请选择自定义治理配置')
          return
        }

        const drafts: GovernanceProcessingScript[] = []
        for (const file of files) {
          const language = detectScriptLanguage(file.name)
          if (!language) {
            toast.warning(`已跳过不支持的脚本类型：${file.name}`)
            continue
          }
          const content = await file.text()
          if (content.length > MAX_PROCESSING_SCRIPT_CHARS) {
            toast.warning(`已跳过过大的脚本：${file.name}`)
            continue
          }
          drafts.push({
            name: file.name,
            language,
            stage: 'post_governance',
            content,
            enabled: false,
            description:
              '导入的处理脚本草案，仅用于治理配置审核，不会在入库链路中自动执行。',
            created_at: new Date().toISOString(),
          })
        }

        if (!drafts.length) {
          toast.error('没有可导入的处理脚本，仅支持 .js/.ts/.py/.rs')
          return
        }

        const existing = prof.payload.processing_scripts ?? []
        const byKey = new Map<string, GovernanceProcessingScript>()
        for (const item of existing)
          byKey.set(`${item.language}:${item.name}`, item)
        for (const item of drafts)
          byKey.set(`${item.language}:${item.name}`, item)
        const nextScripts = Array.from(byKey.values())
        if (nextScripts.length > 10) {
          toast.error('处理脚本最多保留 10 个，请先在治理配置中清理旧脚本')
          return
        }

        await pipelineApi.updateGovernanceProfile(ref, {
          payload: {
            ...prof.payload,
            processing_scripts: nextScripts,
          },
        })
        toast.success(`已导入 ${drafts.length} 个处理脚本草案`)
      } catch (err: unknown) {
        toast.error(formatApiError(err, '导入处理脚本失败'))
      } finally {
        setImportingScript(false)
      }
    },
    [profileRef]
  )

  const appendBuiltinScripts = useCallback(
    async (templates: BuiltinProcessingScript[]) => {
      const ref = profileRef.trim()
      if (!ref) {
        toast.error('请先选择写入目标治理配置')
        return
      }
      if (!templates.length) {
        toast.error('请先选择至少一个模板')
        return
      }

      setImportingScript(true)
      try {
        const prof = await pipelineApi.getGovernanceProfile(ref)
        if (prof.is_system) {
          toast.error('内置治理配置只读，请选择自定义治理配置')
          return
        }

        const drafts: GovernanceProcessingScript[] = templates.map((tpl) => ({
          name: tpl.name,
          language: tpl.language,
          stage: tpl.stage,
          content: tpl.content,
          enabled: false,
          description: tpl.description,
          created_at: new Date().toISOString(),
        }))

        const existing = prof.payload.processing_scripts ?? []
        const byKey = new Map<string, GovernanceProcessingScript>()
        for (const item of existing)
          byKey.set(`${item.language}:${item.name}`, item)
        for (const item of drafts)
          byKey.set(`${item.language}:${item.name}`, item)
        const nextScripts = Array.from(byKey.values())
        if (nextScripts.length > 10) {
          toast.error('处理脚本最多保留 10 个，请先在治理配置中清理旧脚本')
          return
        }

        await pipelineApi.updateGovernanceProfile(ref, {
          payload: {
            ...prof.payload,
            processing_scripts: nextScripts,
          },
        })
        toast.success(`已从模板库添加 ${drafts.length} 个处理脚本`)
        setTemplateLibraryOpen(false)
        setSelectedTemplateKeys(new Set())
      } catch (err: unknown) {
        toast.error(formatApiError(err, '从模板库添加处理脚本失败'))
      } finally {
        setImportingScript(false)
      }
    },
    [profileRef]
  )

  const filteredTemplates = useMemo(() => {
    const all = templateLibraryQuery.data?.items ?? []
    const q = templateSearch.trim().toLowerCase()
    if (!q) return all
    return all.filter((tpl) =>
      [tpl.name, tpl.description, tpl.key, ...(tpl.tags ?? [])]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(q))
    )
  }, [templateLibraryQuery.data?.items, templateSearch])

  const toggleTemplateSelection = useCallback((key: string) => {
    setSelectedTemplateKeys((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const confirmAddFromTemplateLibrary = useCallback(() => {
    const all = templateLibraryQuery.data?.items ?? []
    const picked = all.filter((tpl) => selectedTemplateKeys.has(tpl.key))
    detachPromise(appendBuiltinScripts(picked))
  }, [
    appendBuiltinScripts,
    selectedTemplateKeys,
    templateLibraryQuery.data?.items,
  ])

  const applyToProfile = useCallback(async () => {
    const ref = profileRef.trim()
    if (!ref) {
      toast.error('请选择一个自定义治理配置')
      return
    }
    if (!selectedCandidates.length) {
      toast.error('请先勾选要写入的行')
      return
    }

    setLoading(true)
    try {
      const prof = await pipelineApi.getGovernanceProfile(ref)
      if (prof.is_system) {
        toast.error('内置治理配置只读，请选择自定义治理配置')
        return
      }

      const existingRules: RegexRuleModel[] = Array.isArray(
        prof.payload?.regex_rules
      )
        ? prof.payload.regex_rules
        : []
      const patterns = new Set(
        existingRules.map((r) => String(r?.pattern || ''))
      )
      const nextRules = [...existingRules]

      let added = 0
      for (const c of selectedCandidates) {
        const rule =
          buildLineRegexRule(String(c.sample || '')) ||
          buildLineRegexRule(String(c.signature || ''))
        if (!rule) continue
        if (patterns.has(rule.pattern)) continue
        patterns.add(rule.pattern)
        nextRules.push(rule)
        added += 1
      }

      if (!added) {
        toast.info('没有新增规则（可能已存在或候选为空）')
        return
      }

      await pipelineApi.updateGovernanceProfile(ref, {
        payload: {
          ...prof.payload,
          regex_rules: nextRules,
        },
      })
      toast.success(`已写入治理配置：新增 ${added} 条规则`)
      router.push('/data-governance/profiles')
    } catch (err: unknown) {
      toast.error(formatApiError(err, '写入治理配置失败'))
    } finally {
      setLoading(false)
    }
  }, [profileRef, router, selectedCandidates])

  return (
    <PageScaffold
      title="重复内容治理"
      badge="规则生成"
      iconImage="profile-discovery"
      icon={Hash}
      iconColor="text-success"
      description="跨文档识别页眉、页脚、导航和免责声明等反复出现的行,可一键写入自定义治理配置。"
      size="full"
      density="system-dense"
      showHeader={false}
      topClassName="relative z-10 w-full max-w-none px-3 md:px-4 lg:px-5 pt-3 md:pt-4 pb-2 md:pb-3"
      bodyContainerClassName="max-w-none"
      top={
        <KnowledgeOpsHero
          iconImage="profile-discovery"
          title="重复内容治理"
          description="跨文档识别页眉、页脚、导航和免责声明等反复出现的行，可一键写入自定义治理配置。"
          summary={
            <div className="grid gap-2 sm:grid-cols-2">
              <div className={KNOWLEDGE_OPS_SUMMARY_PANEL_CLASS}>
                <span className="inline-flex items-center gap-1.5">
                  <span className="size-1 rounded-full bg-info/70" aria-hidden />
                  候选
                </span>
                <span className="font-mono tabular-nums text-foreground">
                  {candidates.length}
                </span>
                <span className="h-3.5 w-px bg-border/70" />
                <span>已选</span>
                <span className="font-mono tabular-nums text-foreground">
                  {selectedCandidates.length}
                </span>
              </div>
              <KnowledgeOpsFlowCard
                steps={[
                  { icon: FileSearch, label: '扫描文档' },
                  { icon: Wand2, label: '聚合候选' },
                  { icon: Database, label: '写入配置' },
                ]}
              />
            </div>
          }
          actions={
            <>
              <Button
                variant="outline"
                size="sm"
                className="h-10 gap-2 rounded-xl border-border/60 bg-card px-4 text-[13px] font-semibold shadow-subtle"
                onClick={refreshMeta}
                disabled={loadingMeta}
              >
                <RefreshCw
                  className={cn(
                    'w-4 h-4',
                    loadingMeta && 'animate-spin motion-reduce:animate-none'
                  )}
                />
                刷新
              </Button>
              <Button
                size="sm"
                className="h-10 gap-2 rounded-xl px-5 text-[13px] font-semibold shadow-soft"
                onClick={() => detachPromise(runLearn())}
                disabled={loading}
              >
                {loading ? (
                  <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" />
                ) : (
                  <Wand2 className="w-4 h-4" />
                )}
                扫描
              </Button>
            </>
          }
        />
      }
    >
      <input
        ref={uploadInputRef}
        type="file"
        multiple
        accept={SCRIPT_UPLOAD_ACCEPT}
        className="sr-only"
        onChange={(event) => {
          const files = Array.from(event.target.files || [])
          event.target.value = ''
          detachPromise(importProcessingScripts(files))
        }}
      />
      <div
        className={cn(
          'mt-6 grid transition-[grid-template-columns,gap] duration-200 ease-out',
          controlsCollapsed
            ? 'gap-2 xl:grid-cols-[0px_minmax(0,1fr)]'
            : 'gap-6 xl:grid-cols-[420px_minmax(0,1fr)]'
        )}
      >
        <aside className="relative min-w-0 xl:sticky xl:top-3 xl:self-start">
          <Button
            type="button"
            variant="outline"
            size="icon"
            className={cn(
              'absolute top-5 z-10 hidden size-8 rounded-full border-border/70 bg-card/95 text-muted-foreground shadow-soft backdrop-blur hover:bg-background hover:text-foreground xl:inline-flex',
              controlsCollapsed ? 'right-[-26px]' : 'right-[-18px]'
            )}
            aria-label={controlsCollapsed ? '展开参数栏' : '收起参数栏'}
            onClick={() => setControlsCollapsed((value) => !value)}
          >
            <ChevronsLeft
              className={cn(
                'size-4 transition-transform',
                controlsCollapsed && 'rotate-180'
              )}
            />
          </Button>

          {controlsCollapsed ? (
            <div aria-hidden className="hidden xl:block" />
          ) : (
            <div
              data-testid="common-lines-control-panel"
              className="overflow-hidden rounded-2xl border border-border/60 bg-card shadow-subtle"
            >
              <section className="relative border-b border-border/55 from-success/[0.07] via-background to-transparent px-5 py-5 dark:from-success/[0.10]">
                <span
                  aria-hidden
                  className="absolute left-0 top-4 bottom-4 w-[2px] rounded-full bg-success/70"
                />
                <div>
                  <div className="flex items-start gap-3">
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-success/20 bg-success/[0.08] text-success">
                      <FileSearch className="size-4" />
                    </div>
                    <div className="min-w-0">
                      <h2 className="text-[16px] font-semibold tracking-[-0.01em] text-foreground">
                        识别范围
                      </h2>
                      <p className="mt-2 text-[13px] leading-6 text-muted-foreground/90">
                        优先扫描治理前原始解析结果中的重复行,适合发现页眉、页脚、导航和免责声明。
                      </p>
                    </div>
                  </div>
                </div>
              </section>

              <section className="border-b border-border/55">
                <div className="flex items-center gap-2 px-5 py-4">
                  <Database className="size-5 text-muted-foreground/80" />
                  <h2 className="text-[16px] font-semibold tracking-[-0.01em] text-foreground">
                    目标
                  </h2>
                </div>
                <div className="space-y-4 px-5 pb-5">
                  <div className="min-w-0 space-y-2">
                    <Label className="text-[12px] font-semibold text-foreground/85">
                      数据集
                    </Label>
                    <Select
                      value={datasetId || ''}
                      onValueChange={(v) => setDatasetId(v)}
                    >
                      <SelectTrigger className="h-11 rounded-lg border-border/60 bg-card text-[14px] shadow-none hover:border-success/40 focus:border-success/60 focus-visible:ring-2 focus-visible:ring-success/20">
                        <SelectValue placeholder="选择数据集" />
                      </SelectTrigger>
                      <SelectContent>
                        {datasets.length ? (
                          datasets.map((d) => (
                            <SelectItem key={d.id} value={String(d.id)}>
                              {d.name}
                            </SelectItem>
                          ))
                        ) : (
                          <SelectItem value="__none__" disabled>
                            暂无数据集
                          </SelectItem>
                        )}
                      </SelectContent>
                    </Select>
                    <p className="text-[11px] leading-5 text-muted-foreground/72">
                      依赖入库时开启{' '}
                      <span className="rounded bg-muted/60 px-1 py-0.5 font-mono text-[10.5px] text-foreground/85">
                        persist_parsed_content
                      </span>
                    </p>
                  </div>

                  <div className="min-w-0 space-y-2">
                    <Label className="text-[12px] font-semibold text-foreground/85">
                      写入目标治理配置
                    </Label>
                    <Select
                      value={profileRef || ''}
                      onValueChange={(v) => setProfileRef(v)}
                    >
                      <SelectTrigger className="h-11 rounded-lg border-border/60 bg-card text-[14px] shadow-none hover:border-success/40 focus:border-success/60 focus-visible:ring-2 focus-visible:ring-success/20">
                        <SelectValue placeholder="选择自定义治理配置" />
                      </SelectTrigger>
                      <SelectContent>
                        {profiles.length ? (
                          profiles.map((p) => (
                            <SelectItem
                              key={p.key}
                              value={String(p.id || p.key)}
                            >
                              {p.name}
                            </SelectItem>
                          ))
                        ) : (
                          <SelectItem value="__none__" disabled>
                            暂无自定义治理配置(请先创建)
                          </SelectItem>
                        )}
                      </SelectContent>
                    </Select>
                    <p className="text-[11px] leading-5 text-muted-foreground/72">
                      写入后可在{' '}
                      <span className="rounded bg-muted/60 px-1 py-0.5 font-mono text-[10.5px] text-foreground/85">
                        /data-governance/profiles
                      </span>{' '}
                      编辑
                    </p>
                  </div>

                  <div className="rounded-xl border border-dashed border-success/25 bg-success/[0.04] p-3">
                    <div className="flex items-start gap-3">
                      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-success/[0.10] text-success">
                        <Upload className="size-4" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="text-[12px] font-semibold text-foreground/85">
                          导入处理脚本
                        </div>
                        <p className="mt-1 text-[11px] leading-5 text-muted-foreground/75">
                          只导入 JS/TS、Python、Rust
                          脚本草案到当前治理配置，用于处理解析后或治理后的文本；不上传文档，也不会自动执行。
                        </p>
                      </div>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="mt-3 h-9 w-full gap-2 rounded-lg border-success/25 bg-card text-[12px] font-semibold text-success shadow-none hover:bg-success/[0.08] hover:text-success"
                      disabled={
                        importingScript || loading || !profileRef.trim()
                      }
                      onClick={() => uploadInputRef.current?.click()}
                    >
                      {importingScript ? (
                        <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" />
                      ) : (
                        <Upload className="size-3.5" />
                      )}
                      {importingScript ? '导入中' : '导入脚本草案'}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="mt-2 h-9 w-full gap-2 rounded-lg border-success/25 bg-card text-[12px] font-semibold text-success shadow-none hover:bg-success/[0.08] hover:text-success"
                      disabled={
                        importingScript ||
                        loading ||
                        !profileRef.trim() ||
                        templateLibraryQuery.isFetching
                      }
                      onClick={() => {
                        setSelectedTemplateKeys(new Set())
                        setTemplateSearch('')
                        setTemplateLibraryOpen(true)
                      }}
                    >
                      <Sparkles className="size-3.5" />
                      从模板库选择
                    </Button>
                  </div>
                </div>
              </section>

              <section>
                <div className="flex items-center gap-2 px-5 py-4">
                  <Sliders className="size-5 text-muted-foreground/80" />
                  <h2 className="text-[16px] font-semibold tracking-[-0.01em] text-foreground">
                    参数
                  </h2>
                </div>
                <div className="grid grid-cols-2 gap-3 px-5 pb-4">
                  <div className="min-w-0 space-y-1.5">
                    <Label className="text-[11px] font-medium text-foreground/85">
                      扫描文档数
                    </Label>
                    <Input
                      type="number"
                      value={String(limitDocs)}
                      onChange={(e) =>
                        setLimitDocs(Number(e.target.value || 0))
                      }
                      className="h-9 rounded-lg border-border/60 bg-card text-[13px] tabular-nums shadow-none"
                    />
                  </div>

                  <div className="min-w-0 space-y-1.5">
                    <Label className="text-[11px] font-medium text-foreground/85">
                      最少命中文档
                    </Label>
                    <Input
                      type="number"
                      value={String(minDocs)}
                      onChange={(e) => setMinDocs(Number(e.target.value || 0))}
                      className="h-9 rounded-lg border-border/60 bg-card text-[13px] tabular-nums shadow-none"
                    />
                  </div>

                  <div className="min-w-0 space-y-1.5">
                    <Label className="text-[11px] font-medium text-foreground/85">
                      最小命中比例
                    </Label>
                    <Input
                      type="number"
                      step="0.1"
                      value={String(minRatio)}
                      onChange={(e) => setMinRatio(Number(e.target.value || 0))}
                      className="h-9 rounded-lg border-border/60 bg-card text-[13px] tabular-nums shadow-none"
                    />
                  </div>

                  <div className="min-w-0 space-y-1.5">
                    <Label className="text-[11px] font-medium text-foreground/85">
                      最大行长度
                    </Label>
                    <Input
                      type="number"
                      value={String(maxLineLength)}
                      onChange={(e) =>
                        setMaxLineLength(Number(e.target.value || 0))
                      }
                      className="h-9 rounded-lg border-border/60 bg-card text-[13px] tabular-nums shadow-none"
                    />
                  </div>

                  <div className="col-span-2 min-w-0 space-y-1.5">
                    <Label className="text-[11px] font-medium text-foreground/85">
                      最多候选数
                    </Label>
                    <Input
                      type="number"
                      value={String(maxCandidates)}
                      onChange={(e) =>
                        setMaxCandidates(Number(e.target.value || 0))
                      }
                      className="h-9 rounded-lg border-border/60 bg-card text-[13px] tabular-nums shadow-none"
                    />
                  </div>
                </div>

                <label className="flex cursor-pointer items-start gap-3 border-t border-border/50 bg-muted/[0.14] px-5 py-3 text-[12px] leading-5 text-foreground/85 transition-colors hover:bg-muted/[0.22]">
                  <Checkbox
                    checked={useOriginal}
                    onCheckedChange={(v) => setUseOriginal(Boolean(v))}
                    className="mt-0.5 data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground"
                  />
                  <span>优先基于治理前的原始解析结果进行识别</span>
                </label>
              </section>
            </div>
          )}
        </aside>

        <section className="min-w-0">
          <div className="flex min-h-[760px] flex-col overflow-hidden rounded-2xl border border-border/60 bg-card shadow-subtle">
            <div className="flex min-h-[76px] flex-col gap-3 border-b border-border/60 bg-card px-7 py-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-border/60 bg-muted/30 text-muted-foreground">
                  <Sparkles className="size-4" />
                </div>
                <h2 className="text-[17px] font-semibold tracking-[-0.01em] text-foreground">
                  候选结果
                </h2>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                {resp && candidates.length ? (
                  <>
                    <span className="inline-flex h-9 items-center rounded-lg border border-border/60 bg-background px-3 text-[12px] font-medium tabular-nums text-foreground">
                      共 {sortedCandidates.length}
                    </span>
                    <span className="inline-flex h-9 items-center rounded-lg border border-success/25 bg-success/[0.08] px-3 text-[12px] font-medium tabular-nums text-success">
                      已选 {selectedCandidates.length}
                    </span>
                    <span className="inline-flex h-9 items-center rounded-lg border border-border/60 bg-muted/30 px-3 text-[12px] font-medium tabular-nums text-muted-foreground">
                      扫描 {resp.used_documents}/{resp.total_documents} 文档
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-9 rounded-lg px-3 text-[12px] font-medium text-muted-foreground shadow-none hover:bg-muted/60 hover:text-foreground"
                      onClick={() => toggleAll(true)}
                    >
                      全选
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-9 rounded-lg px-3 text-[12px] font-medium text-muted-foreground shadow-none hover:bg-muted/60 hover:text-foreground"
                      onClick={() => toggleAll(false)}
                    >
                      全不选
                    </Button>
                    <Button
                      size="sm"
                      className="h-9 gap-2 rounded-lg px-4 text-[12px] font-semibold shadow-soft"
                      onClick={() => detachPromise(applyToProfile())}
                      disabled={loading || !selectedCandidates.length}
                    >
                      {loading ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                      ) : (
                        <Hash className="w-3.5 h-3.5" />
                      )}
                      写入配置 ({selectedCandidates.length})
                    </Button>
                  </>
                ) : null}
                <span className="text-[14px] font-medium text-muted-foreground">
                  {resp
                    ? sortedCandidates.length
                      ? `${sortedCandidates.length} 条数据`
                      : '暂无数据'
                    : '暂无数据'}
                </span>
              </div>
            </div>

            {resp && candidates.length ? (
              <div className="overflow-x-auto">
                <div className="min-w-[720px]">
                  <div className="grid grid-cols-[44px_minmax(0,1fr)_110px_110px] items-center gap-3 border-b border-border/60 bg-muted/[0.18] px-5 py-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground/85">
                    <div></div>
                    <div>重复行预览</div>
                    <div className="text-right">命中文档</div>
                    <div className="text-right">命中比例</div>
                  </div>
                  <div className="divide-y divide-border/45">
                    {sortedCandidates.map((c) => {
                      const sig = String(c.signature || '')
                      const checked = Boolean(selected[sig])
                      const ratio = Number(c.ratio || 0)
                      const ratioToneClass =
                        ratio >= 0.8
                          ? 'text-success'
                          : ratio >= 0.5
                            ? 'text-warning'
                            : 'text-muted-foreground'
                      return (
                        <div
                          key={sig}
                          className={cn(
                            'group grid grid-cols-[44px_minmax(0,1fr)_110px_110px] items-start gap-3 px-5 py-3 transition-colors',
                            checked
                              ? 'bg-success/[0.06] hover:bg-success/[0.10]'
                              : 'bg-transparent hover:bg-muted/[0.16]'
                          )}
                        >
                          <div className="pt-0.5">
                            <Checkbox
                              checked={checked}
                              onCheckedChange={(v) =>
                                setSelected((prev) => ({
                                  ...prev,
                                  [sig]: Boolean(v),
                                }))
                              }
                            />
                          </div>
                          <div className="min-w-0">
                            <div
                              className={cn(
                                'line-clamp-2 break-words text-[13px] leading-[1.45rem] transition-colors',
                                checked
                                  ? 'text-foreground'
                                  : 'text-foreground/90 group-hover:text-foreground'
                              )}
                              title={c.sample || c.signature}
                            >
                              {c.sample || c.signature}
                            </div>
                            <div
                              className="mt-1 truncate font-mono text-[11px] text-muted-foreground/65"
                              title={c.signature}
                            >
                              {c.signature}
                            </div>
                          </div>
                          <div className="pt-0.5 text-right font-mono text-[12px] tabular-nums text-foreground/85">
                            {c.docs}
                          </div>
                          <div
                            className={cn(
                              'pt-0.5 text-right font-mono text-[12px] font-medium tabular-nums',
                              ratioToneClass
                            )}
                          >
                            {ratio.toFixed(2)}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-1 flex-col">
                <div className="flex min-h-[410px] flex-none flex-col items-center justify-center px-6 py-10 text-center">
                  <div className="relative mb-7 flex size-24 items-center justify-center rounded-full border border-success/20 bg-success/[0.08] text-success">
                    <span
                      aria-hidden
                      className="absolute inset-2 rounded-full bg-success/[0.05]"
                    />
                    <Search className="relative size-10" />
                    <span
                      aria-hidden
                      className="absolute -left-4 top-12 text-[28px] font-medium text-muted-foreground/25"
                    >
                      +
                    </span>
                    <span
                      aria-hidden
                      className="absolute -right-5 top-8 size-2 rounded-full bg-success/25"
                    />
                    <span
                      aria-hidden
                      className="absolute -right-2 bottom-5 size-1.5 rounded-full bg-muted-foreground/25"
                    />
                  </div>
                  <div className="text-[18px] font-semibold tracking-[-0.01em] text-foreground">
                    {resp ? '没有发现候选重复行' : '尚未生成候选结果'}
                  </div>
                  <p className="mt-3 max-w-xl text-[14px] leading-6 text-muted-foreground">
                    {resp
                      ? '可尝试降低最小命中比例、减少最少命中文档数,或增加扫描文档数。'
                      : '点击右上角「扫描」开始生成候选行,再勾选需要写入治理配置的规则。'}
                  </p>
                </div>

                {resp ? null : (
                  <div className="px-10 pb-12">
                    <div className="mx-auto mb-10 h-px max-w-5xl border-t border-dashed border-border/70" />
                    <div className="mx-auto grid max-w-5xl grid-cols-1 items-center gap-4 md:grid-cols-[1fr_auto_1fr_auto_1fr]">
                      {emptyWorkflowSteps.map((step, index) => {
                        const StepIcon = step.icon
                        return (
                          <div key={step.title} className="contents">
                            <div className="rounded-xl border border-border/60 bg-background px-6 py-5 shadow-subtle">
                              <div className="flex items-start gap-4">
                                <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-success/[0.10] text-success">
                                  <StepIcon className="size-5" />
                                </div>
                                <div className="min-w-0">
                                  <div className="text-[15px] font-semibold text-foreground">
                                    {step.title}
                                  </div>
                                  <p className="mt-1.5 text-[12px] leading-5 text-muted-foreground">
                                    {step.description}
                                  </p>
                                </div>
                              </div>
                            </div>
                            {index < emptyWorkflowSteps.length - 1 ? (
                              <ArrowRight className="mx-auto hidden size-7 text-success md:block" />
                            ) : null}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>
      </div>

      <Dialog
        open={templateLibraryOpen}
        onOpenChange={(open) => {
          setTemplateLibraryOpen(open)
          if (!open) {
            setSelectedTemplateKeys(new Set())
            setTemplateSearch('')
          }
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>从内置模板库选择处理脚本</DialogTitle>
            <DialogDescription>
              选中的脚本会被添加到当前治理配置的 processing_scripts 中,用于审计与版本管理;入库管道不会自动执行模板代码,可在自定义服务中复用。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Search className="size-4 text-muted-foreground" />
              <Input
                value={templateSearch}
                onChange={(event) => setTemplateSearch(event.target.value)}
                placeholder="按名称、描述、tag 搜索..."
                className="h-9 flex-1 rounded-lg text-[13px]"
              />
            </div>

            <div className="max-h-[480px] overflow-y-auto rounded-lg border border-border/60">
              {templateLibraryQuery.isLoading ? (
                <div className="flex items-center justify-center gap-2 py-12 text-[13px] text-muted-foreground">
                  <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                  正在加载模板库...
                </div>
              ) : templateLibraryQuery.error ? (
                <div className="px-4 py-8 text-center text-[13px] text-destructive">
                  加载模板库失败:
                  {formatApiError(templateLibraryQuery.error, '未知错误')}
                </div>
              ) : filteredTemplates.length === 0 ? (
                <div className="px-4 py-8 text-center text-[13px] text-muted-foreground">
                  {templateSearch ? '没有匹配的模板' : '模板库为空'}
                </div>
              ) : (
                <ul className="divide-y divide-border/60">
                  {filteredTemplates.map((tpl) => {
                    const picked = selectedTemplateKeys.has(tpl.key)
                    return (
                      <li
                        key={tpl.key}
                        className={cn(
                          'px-4 py-3 transition-colors hover:bg-muted/40',
                          picked && 'bg-success/[0.06]'
                        )}
                      >
                        <div className="flex items-start gap-3">
                          <Checkbox
                            checked={picked}
                            onCheckedChange={() =>
                              toggleTemplateSelection(tpl.key)
                            }
                            onClick={(e) => e.stopPropagation()}
                            aria-label={`选择 ${tpl.name}`}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-[13px] font-semibold text-foreground">
                                {tpl.name}
                              </span>
                              <Badge
                                variant="secondary"
                                className="h-5 rounded-md px-1.5 text-[10px] font-medium uppercase"
                              >
                                {tpl.language}
                              </Badge>
                              <Badge
                                variant="outline"
                                className="h-5 rounded-md px-1.5 text-[10px] font-medium"
                              >
                                {tpl.stage === 'post_parse'
                                  ? '解析后'
                                  : '治理后'}
                              </Badge>
                            </div>
                            <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                              {tpl.description}
                            </p>
                            {tpl.tags?.length ? (
                              <div className="mt-1.5 flex flex-wrap gap-1">
                                {tpl.tags
                                  .filter((t) => t !== 'builtin')
                                  .slice(0, 6)
                                  .map((tag) => (
                                    <span
                                      key={tag}
                                      className="rounded bg-muted/60 px-1.5 py-[1px] text-[10px] text-muted-foreground"
                                    >
                                      {tag}
                                    </span>
                                  ))}
                              </div>
                            ) : null}
                          </div>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-2">
            <div className="mr-auto self-center text-[12px] text-muted-foreground">
              已选 {selectedTemplateKeys.size} / {filteredTemplates.length}
            </div>
            <Button
              variant="outline"
              onClick={() => setTemplateLibraryOpen(false)}
              disabled={importingScript}
            >
              取消
            </Button>
            <Button
              onClick={confirmAddFromTemplateLibrary}
              disabled={importingScript || selectedTemplateKeys.size === 0}
              className="gap-2"
            >
              {importingScript ? (
                <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
              ) : (
                <Sparkles className="size-4" />
              )}
              添加到治理配置
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageScaffold>
  )
}
