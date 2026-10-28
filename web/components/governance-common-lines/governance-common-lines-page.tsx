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
} from '@/components/icons'

import { useRouter } from '@/i18n/navigation'
import { OperationalWorkspace, WorkspaceTableScroll, DirectoryWorkspace, WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'

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
  GovernanceProfileOut,
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

async function listWritableCommonLineProfiles(): Promise<GovernanceProfileSummary[]> {
  const response = await pipelineApi.listGovernanceProfiles(COMMON_LINES_PROFILE_PARAMS)
  return response.items.filter(profile => !profile.is_system)
}

export function GovernanceCommonLinesPage() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const cacheUpdatedProfile = useCallback((ref: string, profile: GovernanceProfileOut) => {
    queryClient.setQueryData(queryKeys.governance.profile(ref), profile)
    void queryClient.invalidateQueries({ queryKey: ['governance', 'profile-resolved'] })
  }, [queryClient])
  const uploadInputRef = useRef<HTMLInputElement | null>(null)

  const [datasetId, setDatasetId] = useState<string>('')
  const [profileRef, setProfileRef] = useState<string>('')

  const [limitDocs, setLimitDocs] = useState(20)
  const [useOriginal, setUseOriginal] = useState(true)
  const [minDocs, setMinDocs] = useState(3)
  const [minRatio, setMinRatio] = useState(0.5)
  const [maxLineLength, setMaxLineLength] = useState(120)
  const [maxCandidates, setMaxCandidates] = useState(50)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [pane, setPane] = useState<'directory' | 'detail'>('directory')
  const [activeTab, setActiveTab] = useState('candidates')
  const [previewSignature, setPreviewSignature] = useState<string | null>(null)
  const [editedPatterns, setEditedPatterns] = useState<Record<string, string>>({})
  const [operationError, setOperationError] = useState<string | null>(null)

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
    setOperationError(null)
    setResp(null)
    setSelected({})
    try {
      const out = await pipelineApi.learnCommonLines({
        dataset_id: dsId,
        limit_docs: Math.max(2, Math.min(50, Number(limitDocs || 20))),
        use_original: Boolean(useOriginal),
        min_docs: Math.max(2, Math.min(50, Number(minDocs || 3))),
        min_ratio: Math.max(0, Math.min(1, minRatio)),
        max_line_length: Math.max(
          20,
          Math.min(400, Number(maxLineLength || 120))
        ),
        max_candidates: Math.max(1, Math.min(200, Number(maxCandidates || 50))),
      })
      setResp(out)
      setPane('detail')
      setActiveTab('candidates')
    } catch (err: unknown) {
      setOperationError(formatApiError(err, '扫描重复行失败'))
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
      setOperationError(null)
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

        const updated = await pipelineApi.updateGovernanceProfile(ref, {
          payload: {
            ...prof.payload,
            processing_scripts: nextScripts,
          },
        })
        cacheUpdatedProfile(ref, updated)
        toast.success(`已导入 ${drafts.length} 个处理脚本草案`)
      } catch (err: unknown) {
        setOperationError(formatApiError(err, '导入处理脚本失败'))
      } finally {
        setImportingScript(false)
      }
    },
    [profileRef, cacheUpdatedProfile]
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
      setOperationError(null)
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

        const updated = await pipelineApi.updateGovernanceProfile(ref, {
          payload: {
            ...prof.payload,
            processing_scripts: nextScripts,
          },
        })
        cacheUpdatedProfile(ref, updated)
        toast.success(`已从模板库添加 ${drafts.length} 个处理脚本`)
        setTemplateLibraryOpen(false)
        setSelectedTemplateKeys(new Set())
      } catch (err: unknown) {
        setOperationError(formatApiError(err, '从模板库添加处理脚本失败'))
      } finally {
        setImportingScript(false)
      }
    },
    [profileRef, cacheUpdatedProfile]
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
    setOperationError(null)
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
        rule.pattern = editedPatterns[c.signature] ?? rule.pattern
        if (!rule.pattern.trim()) throw new Error('正则表达式不能为空')
        if (patterns.has(rule.pattern)) continue
        patterns.add(rule.pattern)
        nextRules.push(rule)
        added += 1
      }

      if (!added) {
        toast.info('没有新增规则（可能已存在或候选为空）')
        return
      }

      const updated = await pipelineApi.updateGovernanceProfile(ref, {
        payload: {
          ...prof.payload,
          regex_rules: nextRules,
        },
      })
      cacheUpdatedProfile(ref, updated)
      setActiveTab('saved')
      setPane('detail')
      toast.success(`已写入治理配置：新增 ${added} 条规则`)
    } catch (err: unknown) {
      setOperationError(formatApiError(err, '写入治理配置失败'))
    } finally {
      setLoading(false)
    }
  }, [profileRef, selectedCandidates, editedPatterns, cacheUpdatedProfile])

  const profileDetail = useQuery({ queryKey: queryKeys.governance.profile(profileRef), enabled: Boolean(profileRef), queryFn: () => pipelineApi.getGovernanceProfile(profileRef) })
  const targetProfileLabel = profileDetail.data?.name ?? profiles.find(item => item.id === profileRef || item.key === profileRef)?.name ?? (profileRef || '未选择配置')
  const savedRules = profileDetail.data?.payload?.regex_rules ?? []
  const previewCandidate = candidates.find(item => item.signature === previewSignature)
  const previewRule = previewCandidate ? buildLineRegexRule(previewCandidate.sample || previewCandidate.signature) : null
  const createTargetProfile = async () => {
    setLoading(true); setOperationError(null)
    try {
      const created = await pipelineApi.createGovernanceProfile(DEFAULT_COMMON_LINES_PROFILE)
      setProfileRef(created.id || created.key)
      await profilesQuery.refetch()
      toast.success('已创建治理配置')
    } catch (error) { setOperationError(formatApiError(error, '创建治理配置失败')) }
    finally { setLoading(false) }
  }
  return <OperationalWorkspace title="重复内容规则" icon="profile-discovery" mode="canvas" context={datasets.find(item => item.id === datasetId)?.name} actions={<><Button variant="outline" onClick={() => setSettingsOpen(true)}>扫描参数</Button><Button onClick={() => { void runLearn() }} disabled={loading || !datasetId}>{loading ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Search />}扫描重复内容</Button></>} toolbar={<><Label htmlFor="common-lines-dataset">数据集</Label><Select value={datasetId} onValueChange={value => { setDatasetId(value); setResp(null); setSelected({}); setEditedPatterns({}) }} disabled={loading || importingScript}><SelectTrigger id="common-lines-dataset" className="w-64 max-w-full"><SelectValue placeholder="选择数据集" /></SelectTrigger><SelectContent>{datasets.map(item => <SelectItem value={item.id} key={item.id}>{item.name}</SelectItem>)}</SelectContent></Select><Button variant="ghost" aria-label="重新读取目录" disabled={loadingMeta} onClick={refreshMeta}><RefreshCw /></Button></>}>
    <input ref={uploadInputRef} type="file" multiple accept={SCRIPT_UPLOAD_ACCEPT} className="sr-only" onChange={event => { const files = Array.from(event.target.files || []); event.target.value = ''; detachPromise(importProcessingScripts(files)) }} />
    {metaError ? <WorkspaceNotice retry={refreshMeta}>{formatApiError(metaError, '加载数据集或治理配置失败')}</WorkspaceNotice> : null}
    {operationError ? <div className="px-4"><WorkspaceNotice>{operationError}</WorkspaceNotice></div> : null}
    <DirectoryWorkspace pane={pane} onPaneChange={setPane} directoryLabel="治理配置" detailLabel="规则与样本" directory={<><div className={ws.directoryHeader}><h2 className={ws.sectionTitle}>目标治理配置</h2><p className={ws.sectionDescription}>选择候选规则的写入位置</p></div>{loadingMeta ? <p className="p-4 text-sm text-muted-foreground">正在读取…</p> : profiles.length ? profiles.map(item => { const ref = item.id || item.key; return <button type="button" className={ws.directoryRow} aria-pressed={profileRef === ref} data-selected={profileRef === ref} disabled={loading || importingScript} key={ref} onClick={() => { setProfileRef(ref); setPane('detail') }}><strong title={item.name}>{item.name}</strong><small>{item.description || item.key}</small></button> }) : <div className="space-y-3 p-4 text-sm"><p className="text-muted-foreground">暂无自定义治理配置</p><Button variant="outline" disabled={loading || !!metaError} onClick={() => { void createTargetProfile() }}>创建治理配置</Button></div>}<div className="flex flex-col gap-2 p-4"><Button variant="outline" disabled={importingScript || loading || !profileRef} onClick={() => uploadInputRef.current?.click()}><Upload />导入脚本草案</Button><Button variant="ghost" disabled={importingScript || loading || !profileRef} onClick={() => { setSelectedTemplateKeys(new Set()); setTemplateSearch(''); setTemplateLibraryOpen(true) }}><Sparkles />从模板库选择</Button><Button variant="ghost" onClick={() => router.push('/data-governance/profiles')}>治理配置目录</Button></div></>}>
      <p className="pt-2 text-[13px] text-muted-foreground">写入目标：{targetProfileLabel}</p><Tabs value={activeTab} onValueChange={setActiveTab}><TabsList className={ws.tabList}><TabsTrigger value="candidates">候选检查 {resp ? ` ${candidates.length}` : ''}</TabsTrigger><TabsTrigger value="saved">已保存规则</TabsTrigger></TabsList>
        <TabsContent value="candidates" className={ws.tabContent}><section className={ws.section}><div className={ws.sectionHeading}><div><h2 className={ws.sectionTitle}>重复行候选</h2>{resp ? <p className={ws.sectionDescription}>已扫描 {resp.used_documents} / {resp.total_documents} 份文档 · 已选 {selectedCandidates.length} 条</p> : null}</div><div className="flex flex-wrap gap-2"><Button variant="ghost" disabled={!candidates.length || loading} onClick={() => toggleAll(true)}>全选</Button><Button variant="ghost" disabled={!selectedCandidates.length || loading} onClick={() => toggleAll(false)}>清空选择</Button><Button disabled={loading || !selectedCandidates.length || !profileRef} onClick={() => { void applyToProfile() }}>写入配置 {selectedCandidates.length ? `(${selectedCandidates.length})` : ''}</Button></div></div>
        {resp ? candidates.length ? <WorkspaceTableScroll label="重复行候选表格" stickyActions><table className={cn(ws.table, 'min-w-[540px]')}><thead><tr><th><span className="sr-only">选择</span></th><th>重复行</th><th>命中文档</th><th>比例</th><th>操作</th></tr></thead><tbody>{sortedCandidates.map(candidate => <tr key={candidate.signature}><td><Checkbox aria-label={`选择重复行 ${candidate.sample || candidate.signature}`} checked={Boolean(selected[candidate.signature])} disabled={loading} onCheckedChange={value => setSelected(prev => ({ ...prev, [candidate.signature]: Boolean(value) }))} /></td><td className="max-w-[500px]"><div className="line-clamp-2" title={candidate.sample || candidate.signature}>{candidate.sample || candidate.signature}</div></td><td className="tabular-nums">{candidate.docs}</td><td className="tabular-nums">{(candidate.ratio * 100).toFixed(0)}%</td><td><Button variant="ghost" onClick={() => setPreviewSignature(candidate.signature)}>预览与编辑</Button></td></tr>)}</tbody></table></WorkspaceTableScroll> : <div className={ws.empty}><h2>没有发现重复行</h2><p>可调整命中比例或增加扫描文档数后重试。</p><Button variant="outline" onClick={() => setSettingsOpen(true)}>调整扫描参数</Button></div> : <div className={ws.empty}><h2>尚未扫描</h2><p>扫描当前数据集的解析正文，检查页眉、页脚等重复内容。</p><Button disabled={loading || !datasetId} onClick={() => { void runLearn() }}>开始扫描</Button></div>}
        </section></TabsContent>
        <TabsContent value="saved" className={ws.tabContent}>{profileDetail.isError ? <WorkspaceNotice retry={() => { void profileDetail.refetch() }}>{formatApiError(profileDetail.error, '规则读取失败')}</WorkspaceNotice> : profileDetail.isLoading ? <p className={ws.empty}>正在读取规则…</p> : <section className={ws.section}><h2 className={ws.sectionTitle}>已保存的正则规则</h2>{savedRules.length ? <div className={ws.tableScroll}><table className={ws.table}><thead><tr><th>正则表达式</th><th>替换文本</th><th>标志</th></tr></thead><tbody>{savedRules.map((rule, index) => <tr key={index}><td className="break-all font-mono">{rule.pattern}</td><td>{rule.repl || '删除匹配内容'}</td><td>{rule.flags}</td></tr>)}</tbody></table></div> : <p className={ws.empty}>当前配置尚未保存正则规则</p>}</section>}</TabsContent>
      </Tabs>
    </DirectoryWorkspace>
    <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}><DialogContent className={ws.dialog}><DialogHeader className={ws.dialogHeader}><DialogTitle>扫描参数</DialogTitle><DialogDescription>识别当前数据集解析正文中的重复行。</DialogDescription></DialogHeader><div className={ws.dialogBody}><div className="grid gap-5 sm:grid-cols-2">{[{ label: '扫描文档数', value: limitDocs, setter: setLimitDocs, min: 2, max: 50 }, { label: '最少命中文档', value: minDocs, setter: setMinDocs, min: 2, max: 50 }, { label: '最小命中比例', value: minRatio, setter: setMinRatio, min: 0, max: 1, step: 0.1 }, { label: '最大行长度', value: maxLineLength, setter: setMaxLineLength, min: 20, max: 400 }, { label: '最多候选数', value: maxCandidates, setter: setMaxCandidates, min: 1, max: 200 }].map(field => <label className="space-y-2 text-sm" key={field.label}><span>{field.label}</span><Input type="number" aria-label={field.label} value={field.value} min={field.min} max={field.max} step={field.step ?? 1} disabled={loading} onChange={event => field.setter(Number(event.target.value))} /></label>)}</div><label className={ws.formRow}><span>优先使用治理前的原始解析结果</span><Checkbox checked={useOriginal} disabled={loading} onCheckedChange={value => setUseOriginal(Boolean(value))} /></label><p className={ws.sectionDescription}>需要文档在入库时保留解析正文。</p></div><DialogFooter className={ws.dialogFooter}><Button variant="outline" onClick={() => setSettingsOpen(false)}>完成</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={previewSignature !== null} onOpenChange={open => { if (!open) setPreviewSignature(null) }}><DialogContent className={ws.dialog}><DialogHeader className={ws.dialogHeader}><DialogTitle>规则与样本</DialogTitle><DialogDescription>修改后的表达式将在“写入配置”时保存。</DialogDescription></DialogHeader><div className={ws.dialogBody}><h2 className={ws.sectionTitle}>样本正文</h2><pre className="my-4 whitespace-pre-wrap break-words text-sm leading-6">{previewCandidate?.sample || previewCandidate?.signature}</pre><Label htmlFor="common-line-pattern">正则表达式</Label><Input id="common-line-pattern" className="mt-2 font-mono" value={previewSignature ? editedPatterns[previewSignature] ?? previewRule?.pattern ?? '' : ''} onChange={event => { if (previewSignature) setEditedPatterns(prev => ({ ...prev, [previewSignature]: event.target.value })) }} /></div><DialogFooter className={ws.dialogFooter}><Button onClick={() => setPreviewSignature(null)}>完成</Button></DialogFooter></DialogContent></Dialog>
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
        <DialogContent className={ws.dialog}>
          <DialogHeader className={ws.dialogHeader}>
            <DialogTitle>从内置模板库选择处理脚本</DialogTitle>
            <DialogDescription>
              选中的脚本会被添加到当前治理配置的 processing_scripts 中,用于审计与版本管理;入库管道不会自动执行模板代码,可在自定义服务中复用。
            </DialogDescription>
          </DialogHeader>

          <div className={ws.dialogBody}>
            {operationError ? <WorkspaceNotice>{operationError}</WorkspaceNotice> : null}
            <div className="flex items-center gap-2">
              <Search className="size-4 text-muted-foreground" />
              <Input
                value={templateSearch}
                onChange={(event) => setTemplateSearch(event.target.value)}
                placeholder="按名称、描述、tag 搜索..."
                className="h-9 flex-1 rounded-lg text-[13px]"
              />
            </div>

            <div className="border-y border-border/60">
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

          <DialogFooter className={ws.dialogFooter}>
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

  </OperationalWorkspace>
}
