'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Hash, Loader2, RefreshCw, Wand2 } from 'lucide-react'

import { useRouter } from '@/i18n/navigation'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
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
      toast.error(formatApiError(err, '加载数据集/Profiles 失败'))
    } finally {
      setLoadingMeta(false)
    }
  }, [datasetId, profileRef])

  useEffect(() => {
    detachPromise(loadMeta())
  }, [loadMeta])

  const candidates: GovernanceCommonLineCandidate[] = useMemo(() => resp?.candidates || [], [resp?.candidates])
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
      toast.error(formatApiError(err, '学习 common lines 失败'))
    } finally {
      setLoading(false)
    }
  }, [datasetId, limitDocs, maxCandidates, maxLineLength, minDocs, minRatio, useOriginal])

  const applyToProfile = useCallback(async () => {
    const ref = profileRef.trim()
    if (!ref) {
      toast.error('请选择一个自定义 Profile')
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
        toast.error('内置 Profile 只读，请选择自定义 Profile')
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
      toast.success(`已写入 Profile：新增 ${added} 条规则`)
      router.push('/data-governance/profiles')
    } catch (err: any) {
      toast.error(formatApiError(err, '写入 Profile 失败'))
    } finally {
      setLoading(false)
    }
  }, [profileRef, router, selectedCandidates])

  return (
    <PageScaffold
      title="Common Lines 学习"
      badge="Governance"
      icon={Hash}
      iconColor="text-primary"
      description="跨文档发现候选样板行（页眉/页脚/导航/免责声明），并一键写入自定义治理 Profile（regex_rules）。"
      size="7xl"
      actions={
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="gap-2 rounded-xl"
            onClick={() => detachPromise(loadMeta())}
            disabled={loadingMeta}
          >
            <RefreshCw className={cn('w-4 h-4', loadingMeta && 'animate-spin motion-reduce:animate-none')} />
            刷新
          </Button>
          <Button
            size="sm"
            className="gap-2 rounded-xl"
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
      <div className="space-y-4">
        <Panel padding="lg" className="rounded-2xl">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>数据集</Label>
              <Select value={datasetId || ''} onValueChange={(v) => setDatasetId(v)}>
                <SelectTrigger className="rounded-xl">
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
              <div className="text-[11px] text-muted-foreground">
                提示：该功能依赖入库时开启 <span className="font-mono">persist_parsed_content</span>。
              </div>
            </div>

            <div className="space-y-2">
              <Label>写入目标 Profile（自定义）</Label>
              <Select value={profileRef || ''} onValueChange={(v) => setProfileRef(v)}>
                <SelectTrigger className="rounded-xl">
                  <SelectValue placeholder="选择自定义 Profile" />
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
                      暂无自定义 Profile（请先创建）
                    </SelectItem>
                  )}
                </SelectContent>
              </Select>
              <div className="text-[11px] text-muted-foreground">
                写入后可在 <span className="font-mono">/data-governance/profiles</span> 中查看/编辑。
              </div>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label>limit_docs</Label>
              <Input
                value={String(limitDocs)}
                onChange={(e) => setLimitDocs(Number(e.target.value || 0))}
                className="rounded-xl"
              />
            </div>
            <div className="space-y-2">
              <Label>min_docs</Label>
              <Input
                value={String(minDocs)}
                onChange={(e) => setMinDocs(Number(e.target.value || 0))}
                className="rounded-xl"
              />
            </div>
            <div className="space-y-2">
              <Label>min_ratio</Label>
              <Input
                value={String(minRatio)}
                onChange={(e) => setMinRatio(Number(e.target.value || 0))}
                className="rounded-xl"
              />
            </div>
            <div className="space-y-2">
              <Label>max_line_length</Label>
              <Input
                value={String(maxLineLength)}
                onChange={(e) => setMaxLineLength(Number(e.target.value || 0))}
                className="rounded-xl"
              />
            </div>
            <div className="space-y-2">
              <Label>max_candidates</Label>
              <Input
                value={String(maxCandidates)}
                onChange={(e) => setMaxCandidates(Number(e.target.value || 0))}
                className="rounded-xl"
              />
            </div>
            <div className="space-y-2">
              <Label>use_original</Label>
              <div className="flex items-center gap-2 rounded-xl border border-border/60 bg-muted/20 px-3 py-2">
                <Checkbox checked={useOriginal} onCheckedChange={(v) => setUseOriginal(Boolean(v))} />
                <div className="text-sm">优先使用原始解析结果（pre-governance）</div>
              </div>
            </div>
          </div>
        </Panel>

        {resp ? (
          <Panel padding="lg" className="rounded-2xl">
            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="text-sm font-semibold text-foreground">候选结果</div>
                <div className="text-[12px] text-muted-foreground mt-1">
                  used_docs <span className="font-mono">{resp.used_documents}</span> / total_with_parsed_content{' '}
                  <span className="font-mono">{resp.total_documents}</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" className="rounded-xl" onClick={() => toggleAll(true)}>
                  全选
                </Button>
                <Button variant="outline" size="sm" className="rounded-xl" onClick={() => toggleAll(false)}>
                  全不选
                </Button>
                <Button
                  size="sm"
                  className="rounded-xl gap-2"
                  onClick={() => detachPromise(applyToProfile())}
                  disabled={loading}
                >
                  {loading ? (
                    <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" />
                  ) : (
                    <Hash className="w-4 h-4" />
                  )}
                  写入 Profile（{selectedCandidates.length}）
                </Button>
              </div>
            </div>

            {candidates.length ? (
              <div className="mt-4 space-y-2">
                {candidates.map((c) => {
                  const sig = String(c.signature || '')
                  const checked = Boolean(selected[sig])
                  return (
                    <div
                      key={sig}
                      className={cn(
                        'rounded-2xl border border-border/60 bg-background/40 p-4 flex items-start gap-3',
                        checked && 'border-primary/40 bg-primary/5'
                      )}
                    >
                      <Checkbox
                        checked={checked}
                        onCheckedChange={(v) => setSelected((prev) => ({ ...prev, [sig]: Boolean(v) }))}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-mono text-muted-foreground">
                            docs={c.docs} · ratio={Number(c.ratio || 0).toFixed(2)}
                          </span>
                        </div>
                        <div className="mt-2 text-sm text-foreground break-words">{c.sample || c.signature}</div>
                        <div className="mt-2 text-[11px] text-muted-foreground font-mono break-all">
                          signature: {c.signature}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="mt-4 text-sm text-muted-foreground">
                未找到候选行。可尝试降低 min_ratio / min_docs 或提高 limit_docs。
              </div>
            )}
          </Panel>
        ) : (
          <Panel padding="lg" className="rounded-2xl">
            <div className="text-sm text-muted-foreground">
              点击“扫描”开始生成候选行，然后勾选并写入治理 Profile。
            </div>
          </Panel>
        )}
      </div>
    </PageScaffold>
  )
}
