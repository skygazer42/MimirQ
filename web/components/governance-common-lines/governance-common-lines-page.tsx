'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Hash, Loader2, RefreshCw, Search, Wand2 } from 'lucide-react'

import { useRouter } from '@/i18n/navigation'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

import { datasetApi, pipelineApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'

import type {
  Dataset,
  GovernanceCommonLineCandidate,
  GovernanceCommonLinesLearnResponse,
  GovernanceProfileSummary,
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

export function GovernanceCommonLinesPage() {
  const router = useRouter()

  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [profiles, setProfiles] = useState<GovernanceProfileSummary[]>([])

  const [datasetId, setDatasetId] = useState<string>('')
  const [profileRef, setProfileRef] = useState<string>('')

  const [limitDocs, setLimitDocs] = useState(20)
  const [useOriginal, setUseOriginal] = useState(true)
  const [minDocs, setMinDocs] = useState(3)
  const [minRatio, setMinRatio] = useState(0.5)
  const [maxLineLength, setMaxLineLength] = useState(120)
  const [maxCandidates, setMaxCandidates] = useState(50)

  const [loading, setLoading] = useState(false)
  const [loadingMeta, setLoadingMeta] = useState(false)
  const [resp, setResp] = useState<GovernanceCommonLinesLearnResponse | null>(null)
  const [selected, setSelected] = useState<Record<string, boolean>>({})

  const loadMeta = useCallback(async () => {
    setLoadingMeta(true)
    try {
      const [dsResp, profResp] = await Promise.all([
        datasetApi.list({ skip: 0, limit: 200 }),
        pipelineApi.listGovernanceProfiles({ include_builtin: false, limit: 200 }),
      ])
      const ds = dsResp.items || []
      const profs = (profResp.items || []).filter((p) => !p.is_system)
      setDatasets(ds)
      setProfiles(profs)
      if (!datasetId && ds.length) setDatasetId(String(ds[0].id || ''))
      if (!profileRef && profs.length) setProfileRef(String(profs[0].id || profs[0].key || ''))
    } catch (err: any) {
      toast.error(formatApiError(err, '加载数据集或治理配置失败'))
    } finally {
      setLoadingMeta(false)
    }
  }, [datasetId, profileRef])

  useEffect(() => {
    detachPromise(loadMeta())
  }, [loadMeta])

  const candidates: GovernanceCommonLineCandidate[] = useMemo(() => resp?.candidates || [], [resp?.candidates])
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
        max_line_length: Math.max(20, Math.min(400, Number(maxLineLength || 120))),
        max_candidates: Math.max(1, Math.min(200, Number(maxCandidates || 50))),
      })
      setResp(out)
      toast.success(`已生成候选行：${(out.candidates || []).length}`)
    } catch (err: any) {
      toast.error(formatApiError(err, '扫描样板行失败'))
    } finally {
      setLoading(false)
    }
  }, [datasetId, limitDocs, maxCandidates, maxLineLength, minDocs, minRatio, useOriginal])

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

      const existingRules: RegexRuleModel[] = Array.isArray(prof.payload?.regex_rules) ? prof.payload.regex_rules : []
      const patterns = new Set(existingRules.map((r) => String(r?.pattern || '')))
      const nextRules = [...existingRules]

      let added = 0
      for (const c of selectedCandidates) {
        const rule = buildLineRegexRule(String(c.sample || '')) || buildLineRegexRule(String(c.signature || ''))
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
    } catch (err: any) {
      toast.error(formatApiError(err, '写入治理配置失败'))
    } finally {
      setLoading(false)
    }
  }, [profileRef, router, selectedCandidates])

  return (
    <PageScaffold
      title="样板行发现"
      badge="规则生成"
      icon={Hash}
      iconColor="text-success"
      description="跨文档识别页眉、页脚、导航和免责声明等重复样板行，可一键写入自定义治理配置。"
      size="full"
      density="system-dense"
      headerClassName="max-w-none"
      bodyContainerClassName="max-w-none"
      actions={
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-2 rounded-lg border-border/55 bg-background/78 text-[12px] shadow-none"
            onClick={() => detachPromise(loadMeta())}
            disabled={loadingMeta}
          >
            <RefreshCw className={cn('w-4 h-4', loadingMeta && 'animate-spin motion-reduce:animate-none')} />
            刷新
          </Button>
          <Button
            size="sm"
            className="h-8 gap-2 rounded-lg text-[12px] shadow-none"
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
        </div>
      }
    >
      <div className="grid gap-0 xl:grid-cols-[320px_minmax(0,1fr)] xl:divide-x xl:divide-border/60">
        <aside className="min-w-0 xl:sticky xl:top-3 xl:self-start xl:pr-5">
          <div className="border-b border-border/55 pb-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground/80">
              识别范围
            </div>
            <div className="mt-1.5 text-[12px] leading-5 text-muted-foreground/78">
              优先扫描治理前原始解析结果中的重复行，适合发现页眉、页脚、导航和免责声明。
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 py-4">
            <div className="min-w-0 space-y-2">
              <Label>数据集</Label>
              <Select value={datasetId || ''} onValueChange={(v) => setDatasetId(v)}>
                <SelectTrigger className="rounded-lg border-border/55 bg-background/82 text-[13px] shadow-none">
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
              <div className="mt-1 text-[11px] leading-5 text-muted-foreground/72">
                提示：该功能依赖入库时开启 <span className="font-mono">persist_parsed_content</span>。
              </div>
            </div>

            <div className="min-w-0 space-y-2">
              <Label>写入目标治理配置</Label>
              <Select value={profileRef || ''} onValueChange={(v) => setProfileRef(v)}>
                <SelectTrigger className="rounded-lg border-border/55 bg-background/82 text-[13px] shadow-none">
                  <SelectValue placeholder="选择自定义治理配置" />
                </SelectTrigger>
                <SelectContent>
                  {profiles.length ? (
                    profiles.map((p) => (
                      <SelectItem key={p.key} value={String(p.id || p.key)}>
                        {p.name}
                      </SelectItem>
                    ))
                  ) : (
                    <SelectItem value="__none__" disabled>
                      暂无自定义治理配置（请先创建）
                    </SelectItem>
                  )}
                </SelectContent>
              </Select>
              <div className="mt-1 text-[11px] leading-5 text-muted-foreground/72">
                写入后可在 <span className="font-mono">/data-governance/profiles</span> 中继续查看和编辑。
              </div>
            </div>

            <div className="min-w-0 space-y-2">
              <Label>扫描文档数</Label>
              <Input
                value={String(limitDocs)}
                onChange={(e) => setLimitDocs(Number(e.target.value || 0))}
                className="rounded-lg border-border/55 bg-background/82 text-[13px] shadow-none"
              />
            </div>

            <div className="min-w-0 space-y-2">
              <Label>最少命中文档</Label>
              <Input
                value={String(minDocs)}
                onChange={(e) => setMinDocs(Number(e.target.value || 0))}
                className="rounded-lg border-border/55 bg-background/82 text-[13px] shadow-none"
              />
            </div>

            <div className="min-w-0 space-y-2">
              <Label>最小命中比例</Label>
              <Input
                value={String(minRatio)}
                onChange={(e) => setMinRatio(Number(e.target.value || 0))}
                className="rounded-lg border-border/55 bg-background/82 text-[13px] shadow-none"
              />
            </div>

            <div className="min-w-0 space-y-2">
              <Label>最大行长度</Label>
              <Input
                value={String(maxLineLength)}
                onChange={(e) => setMaxLineLength(Number(e.target.value || 0))}
                className="rounded-lg border-border/55 bg-background/82 text-[13px] shadow-none"
              />
            </div>

            <div className="min-w-0 space-y-2">
              <Label>最多候选数</Label>
              <Input
                value={String(maxCandidates)}
                onChange={(e) => setMaxCandidates(Number(e.target.value || 0))}
                className="rounded-lg border-border/55 bg-background/82 text-[13px] shadow-none"
              />
            </div>

          </div>

          <div className="border-t border-border/50 pt-3">
            <label className="flex items-start gap-2 text-[13px] leading-5 text-foreground/76">
              <Checkbox checked={useOriginal} onCheckedChange={(v) => setUseOriginal(Boolean(v))} />
              <span>优先基于治理前的原始解析结果进行识别</span>
            </label>
          </div>
        </aside>

        <section className="min-w-0 pt-4 xl:pt-0 xl:pl-5">
          {resp ? (
            <div className="min-w-0">
              <div className="flex flex-col gap-2 border-b border-border/55 pb-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
                <div className="text-[13px] font-semibold text-foreground">候选结果</div>
                <div className="text-[11px] text-muted-foreground/78">
                  共 <span className="font-mono tabular-nums text-foreground/88">{sortedCandidates.length}</span> 条
                  · 已选 <span className="font-mono tabular-nums text-foreground/88">{selectedCandidates.length}</span>{' '}
                  / {sortedCandidates.length}
                  · 已扫描 <span className="font-mono tabular-nums text-foreground/88">{resp.used_documents}</span> /{' '}
                  <span className="font-mono tabular-nums text-foreground/88">{resp.total_documents}</span> 文档
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 rounded-md px-2.5 text-[11px] text-muted-foreground shadow-none hover:bg-muted/55 hover:text-foreground"
                  onClick={() => toggleAll(true)}
                >
                  全选
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 rounded-md px-2.5 text-[11px] text-muted-foreground shadow-none hover:bg-muted/55 hover:text-foreground"
                  onClick={() => toggleAll(false)}
                >
                  全不选
                </Button>
                <Button
                  size="sm"
                  className="h-7 gap-1.5 rounded-md px-2.5 text-[11px] shadow-none"
                  onClick={() => detachPromise(applyToProfile())}
                  disabled={loading}
                >
                  {loading ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                  ) : (
                    <Hash className="w-3.5 h-3.5" />
                  )}
                  写入治理配置（{selectedCandidates.length}）
                </Button>
              </div>
              </div>

              {candidates.length ? (
                <div className="mt-3 overflow-x-auto">
                  <div className="min-w-[640px] border-y border-border/55">
                  <div className="grid grid-cols-[30px_minmax(0,1fr)_76px_76px] items-center gap-2 border-b border-border/50 bg-muted/[0.16] px-2.5 py-2 text-[11px] font-medium tracking-[0.01em] text-muted-foreground/76">
                    <div>选择</div>
                    <div>样板行预览</div>
                    <div className="text-right">命中文档</div>
                    <div className="text-right">命中比例</div>
                  </div>
                  <div className="divide-y divide-border/45">
                    {sortedCandidates.map((c) => {
                      const sig = String(c.signature || '')
                      const checked = Boolean(selected[sig])
                      return (
                        <div
                          key={sig}
                          className={cn(
                              'grid grid-cols-[30px_minmax(0,1fr)_76px_76px] items-start gap-2 px-2.5 py-2.5 transition-colors',
                              checked ? 'bg-primary/[0.06]' : 'bg-transparent hover:bg-muted/[0.12]'
                            )}
                          >
                          <div className="pt-0.5">
                            <Checkbox
                              checked={checked}
                              onCheckedChange={(v) => setSelected((prev) => ({ ...prev, [sig]: Boolean(v) }))}
                            />
                          </div>
                          <div className="min-w-0">
                            <div
                              className="line-clamp-2 break-words text-[12.5px] leading-[1.35rem] text-foreground"
                              title={c.sample || c.signature}
                            >
                              {c.sample || c.signature}
                            </div>
                            <div
                              className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground/66"
                              title={c.signature}
                            >
                              {c.signature}
                            </div>
                          </div>
                          <div className="pt-0.5 text-right text-[10.5px] font-mono tabular-nums text-foreground/84">
                            {c.docs}
                          </div>
                          <div className="pt-0.5 text-right text-[10.5px] font-mono tabular-nums text-foreground/84">
                            {Number(c.ratio || 0).toFixed(2)}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
                </div>
              ) : (
                <div className="mt-4 flex min-h-[200px] flex-col items-center justify-center border border-dashed border-border/60 bg-muted/[0.08] text-center">
                  <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-muted/35 text-muted-foreground">
                    <Search className="h-6 w-6" />
                  </div>
                  <div className="text-sm font-medium text-foreground/80">没有发现候选样板行</div>
                  <div className="mt-2 max-w-lg text-[13px] leading-6 text-muted-foreground">
                    可尝试降低最小命中比例、减少最少命中文档数，或增加扫描文档数。
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex min-h-[220px] flex-col items-center justify-center border border-dashed border-border/60 bg-muted/[0.08] text-center">
              <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-muted/35 text-muted-foreground">
                <Search className="h-7 w-7" />
              </div>
              <div className="text-sm font-medium text-foreground/80">尚未生成候选结果</div>
              <div className="mt-2 max-w-lg text-[13px] leading-6 text-muted-foreground">
                点击右上角“扫描”开始生成候选行，再勾选需要写入治理配置的规则。
              </div>
            </div>
          )}
        </section>
      </div>
    </PageScaffold>
  )
}
