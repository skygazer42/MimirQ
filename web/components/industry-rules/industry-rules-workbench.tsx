'use client'

import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Check,
  Database,
  ExternalLink,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageScaffold } from '@/components/ui/page-scaffold'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatApiError } from '@/lib/api-errors'
import {
  datasetApi,
  industryRulesApi,
  type IndustryRulesetDetail,
} from '@/lib/api'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise } from '@/lib/utils'

type GlossaryEntry = {
  id: string
  term: string
  aliasesText: string
}

type PatternEntry = {
  id: string
  markersText: string
  followup: string
  enabled: boolean
}

type IntentEntry = {
  id: string
  name: string
  keywordsText: string
  route: string
}

type GlossarySuggestion = {
  token: string
  count: number
  source: string
}

type RewritePreviewState = {
  originalQuery: string
  expandedQuery: string
  changed: boolean
}

type ResultSummary = {
  title: string
  detail: string
}

function makeLocalId(prefix: string, seed?: string): string {
  const suffix =
    seed?.trim() || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  return `${prefix}-${suffix}`
}

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return value as Record<string, unknown>
}

function textValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => textValue(item)).filter(Boolean)
}

function splitCommaText(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function glossaryEntriesFromDetail(
  detail: IndustryRulesetDetail
): GlossaryEntry[] {
  return Object.entries(detail.glossary || {})
    .sort((a, b) => a[0].localeCompare(b[0], 'zh-CN'))
    .map(([term, aliases]) => ({
      id: makeLocalId('glossary', term),
      term,
      aliasesText: Array.isArray(aliases) ? aliases.join(', ') : '',
    }))
}

function patternEntriesFromDetail(
  detail: IndustryRulesetDetail
): PatternEntry[] {
  return (detail.patterns || []).map((item, index) => {
    const record = asRecord(item)
    const markers = textList(record.markers ?? record.keywords)
    return {
      id: makeLocalId('pattern', `${index}`),
      markersText: markers.join(', '),
      followup: textValue(record.followup ?? record.followup_template),
      enabled: record.enabled !== false,
    }
  })
}

function intentEntriesFromDetail(detail: IndustryRulesetDetail): IntentEntry[] {
  return (detail.intents || []).map((item, index) => {
    const record = asRecord(item)
    return {
      id: makeLocalId('intent', `${index}`),
      name: textValue(record.name),
      keywordsText: textList(record.keywords).join(', '),
      route: textValue(record.route) || 'default',
    }
  })
}

function buildGlossaryPayload(
  entries: GlossaryEntry[]
): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  for (const entry of entries) {
    const term = entry.term.trim()
    if (!term) continue
    out[term] = splitCommaText(entry.aliasesText)
  }
  return out
}

function buildPatternsPayload(
  entries: PatternEntry[]
): Array<Record<string, unknown>> {
  return entries
    .map((entry) => ({
      markers: splitCommaText(entry.markersText),
      followup: entry.followup.trim(),
      enabled: entry.enabled,
    }))
    .filter((entry) => Array.isArray(entry.markers) && entry.markers.length > 0)
}

function buildIntentsPayload(
  entries: IntentEntry[]
): Array<Record<string, unknown>> {
  return entries
    .map((entry) => ({
      name: entry.name.trim(),
      keywords: splitCommaText(entry.keywordsText),
      route: entry.route.trim() || 'default',
    }))
    .filter((entry) => textValue(entry.name))
}

function suggestionRowsFromPayload(payload: unknown): GlossarySuggestion[] {
  const record = asRecord(payload)
  const rows = Array.isArray(record.glossary_suggestions)
    ? record.glossary_suggestions
    : []
  return rows
    .map((row) => {
      const item = asRecord(row)
      return {
        token: textValue(item.token),
        count: Number(item.count || 0),
        source: textValue(item.source) || 'mining',
      }
    })
    .filter((row) => row.token)
}

function selectedMapValues(selected: Record<string, boolean>): string[] {
  return Object.entries(selected)
    .filter(([, enabled]) => enabled)
    .map(([key]) => key)
}

const INDUSTRY_RULES_DATASET_PARAMS = { limit: 200 } as const

export function IndustryRulesWorkbench() {
  const [selectedRuleset, setSelectedRuleset] = useState('')
  const [selectedDatasetId, setSelectedDatasetId] = useState('')
  const [searchValue, setSearchValue] = useState('')
  const [previewQuery, setPreviewQuery] = useState('授权报错怎么办')

  const [loadingRuleset, setLoadingRuleset] = useState(false)
  const [loadingSuggestions, setLoadingSuggestions] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [savingGlossary, setSavingGlossary] = useState(false)
  const [savingPatterns, setSavingPatterns] = useState(false)
  const [savingIntents, setSavingIntents] = useState(false)

  const [glossaryEntries, setGlossaryEntries] = useState<GlossaryEntry[]>([])
  const [patternEntries, setPatternEntries] = useState<PatternEntry[]>([])
  const [intentEntries, setIntentEntries] = useState<IntentEntry[]>([])
  const [glossarySuggestions, setGlossarySuggestions] = useState<
    GlossarySuggestion[]
  >([])
  const [selectedSuggestionTokens, setSelectedSuggestionTokens] = useState<
    Record<string, boolean>
  >({})
  const [dismissedSuggestionTokens, setDismissedSuggestionTokens] = useState<
    Record<string, boolean>
  >({})
  const [preview, setPreview] = useState<RewritePreviewState | null>(null)
  const [result, setResult] = useState<ResultSummary | null>(null)

  const rulesetsQuery = useQuery({
    queryKey: queryKeys.industryRules.rulesets,
    queryFn: industryRulesApi.listRulesets,
  })
  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.list(INDUSTRY_RULES_DATASET_PARAMS),
    queryFn: () => datasetApi.list(INDUSTRY_RULES_DATASET_PARAMS),
  })

  const rulesets = useMemo(
    () => rulesetsQuery.data?.rulesets || [],
    [rulesetsQuery.data?.rulesets]
  )
  const datasets = useMemo(
    () => datasetsQuery.data?.items || [],
    [datasetsQuery.data?.items]
  )
  const loadingMeta = rulesetsQuery.isFetching || datasetsQuery.isFetching
  const metaError = rulesetsQuery.error || datasetsQuery.error

  const refreshMeta = () => {
    void rulesetsQuery.refetch()
    void datasetsQuery.refetch()
  }

  const loadRulesetDetail = async (rulesetName: string) => {
    const name = rulesetName.trim()
    if (!name) return
    setLoadingRuleset(true)
    try {
      const payload = await industryRulesApi.getRuleset(name)
      setGlossaryEntries(glossaryEntriesFromDetail(payload.ruleset))
      setPatternEntries(patternEntriesFromDetail(payload.ruleset))
      setIntentEntries(intentEntriesFromDetail(payload.ruleset))
      setResult({
        title: '已加载规则集',
        detail: `${payload.ruleset.name} · 术语 ${payload.ruleset.glossary_count} / 模式 ${payload.ruleset.pattern_count} / 意图 ${payload.ruleset.intent_count}`,
      })
    } catch (error) {
      toast.error(formatApiError(error, '加载规则详情失败'))
    } finally {
      setLoadingRuleset(false)
    }
  }

  const loadGlossarySuggestions = async (
    datasetId: string,
    rulesetName: string
  ) => {
    const ds = datasetId.trim()
    const ruleset = rulesetName.trim()
    if (!ds || !ruleset) return
    setLoadingSuggestions(true)
    try {
      const payload = await datasetApi.getAnalysisRuleSuggestions(ds, {
        ruleset,
        limit: 20,
      })
      setGlossarySuggestions(suggestionRowsFromPayload(payload))
      setSelectedSuggestionTokens({})
      setDismissedSuggestionTokens({})
    } catch (error) {
      toast.error(formatApiError(error, '加载规则候选失败'))
    } finally {
      setLoadingSuggestions(false)
    }
  }

  const runPreview = async (query: string, rulesetName: string) => {
    const q = query.trim()
    const ruleset = rulesetName.trim()
    if (!q || !ruleset) {
      setPreview(null)
      return
    }
    setPreviewing(true)
    try {
      const payload = await industryRulesApi.previewRewrite({
        ruleset,
        query: q,
      })
      setPreview({
        originalQuery: payload.original_query,
        expandedQuery: payload.expanded_query,
        changed: payload.changed,
      })
    } catch (error) {
      toast.error(formatApiError(error, '改写预览失败'))
    } finally {
      setPreviewing(false)
    }
  }

  useEffect(() => {
    if (metaError) {
      toast.error(formatApiError(metaError, '加载规则集或数据集失败'))
    }
  }, [metaError])

  useEffect(() => {
    if (!selectedRuleset && rulesets[0]?.name)
      setSelectedRuleset(rulesets[0].name)
  }, [rulesets, selectedRuleset])

  useEffect(() => {
    if (!selectedDatasetId && datasets[0]?.id)
      setSelectedDatasetId(String(datasets[0].id))
  }, [datasets, selectedDatasetId])

  useEffect(() => {
    if (!selectedRuleset.trim()) return
    detachPromise(loadRulesetDetail(selectedRuleset))
  }, [selectedRuleset])

  useEffect(() => {
    if (!selectedRuleset.trim() || !selectedDatasetId.trim()) return
    detachPromise(loadGlossarySuggestions(selectedDatasetId, selectedRuleset))
  }, [selectedDatasetId, selectedRuleset])

  useEffect(() => {
    if (!selectedRuleset.trim() || !previewQuery.trim()) {
      setPreview(null)
      return
    }
    const timer = globalThis.window.setTimeout(() => {
      detachPromise(runPreview(previewQuery, selectedRuleset))
    }, 280)
    return () => globalThis.window.clearTimeout(timer)
  }, [previewQuery, selectedRuleset])

  const selectedRulesetSummary = useMemo(
    () => rulesets.find((item) => item.name === selectedRuleset) || null,
    [rulesets, selectedRuleset]
  )
  const selectedDataset = useMemo(
    () =>
      datasets.find((item) => String(item.id) === selectedDatasetId) || null,
    [datasets, selectedDatasetId]
  )
  const visibleGlossaryEntries = useMemo(() => {
    const keyword = searchValue.trim().toLowerCase()
    if (!keyword) return glossaryEntries
    return glossaryEntries.filter((entry) => {
      const haystack = `${entry.term} ${entry.aliasesText}`.toLowerCase()
      return haystack.includes(keyword)
    })
  }, [glossaryEntries, searchValue])
  const visibleGlossarySuggestions = useMemo(() => {
    const existingTerms = new Set(
      glossaryEntries.map((entry) => entry.term.trim()).filter(Boolean)
    )
    return glossarySuggestions.filter(
      (entry) =>
        !dismissedSuggestionTokens[entry.token] &&
        !existingTerms.has(entry.token)
    )
  }, [dismissedSuggestionTokens, glossaryEntries, glossarySuggestions])
  const selectedSuggestionCount = selectedMapValues(
    selectedSuggestionTokens
  ).length

  const setGlossaryEntry = (id: string, patch: Partial<GlossaryEntry>) => {
    setGlossaryEntries((prev) =>
      prev.map((entry) => (entry.id === id ? { ...entry, ...patch } : entry))
    )
  }

  const setPatternEntry = (id: string, patch: Partial<PatternEntry>) => {
    setPatternEntries((prev) =>
      prev.map((entry) => (entry.id === id ? { ...entry, ...patch } : entry))
    )
  }

  const setIntentEntry = (id: string, patch: Partial<IntentEntry>) => {
    setIntentEntries((prev) =>
      prev.map((entry) => (entry.id === id ? { ...entry, ...patch } : entry))
    )
  }

  const addGlossarySuggestion = (token: string) => {
    const term = token.trim()
    if (!term) return
    setGlossaryEntries((prev) => {
      if (prev.some((entry) => entry.term.trim() === term)) return prev
      return [
        ...prev,
        { id: makeLocalId('glossary', term), term, aliasesText: '' },
      ]
    })
    setDismissedSuggestionTokens((prev) => ({ ...prev, [term]: true }))
  }

  const acceptSelectedSuggestions = () => {
    for (const token of selectedMapValues(selectedSuggestionTokens)) {
      addGlossarySuggestion(token)
    }
    setSelectedSuggestionTokens({})
  }

  const saveGlossary = async () => {
    const ruleset = selectedRuleset.trim()
    if (!ruleset) return
    setSavingGlossary(true)
    try {
      const payload = await industryRulesApi.updateGlossary(ruleset, {
        glossary: buildGlossaryPayload(glossaryEntries),
      })
      setResult({
        title: '已保存术语',
        detail: `${ruleset} · 更新 ${String(payload.updated_count || glossaryEntries.length)} 条术语`,
      })
      toast.success('术语已保存')
      await loadRulesetDetail(ruleset)
    } catch (error) {
      toast.error(formatApiError(error, '保存术语失败'))
    } finally {
      setSavingGlossary(false)
    }
  }

  const savePatterns = async () => {
    const ruleset = selectedRuleset.trim()
    if (!ruleset) return
    setSavingPatterns(true)
    try {
      const payload = await industryRulesApi.updatePatterns(ruleset, {
        patterns: buildPatternsPayload(patternEntries),
      })
      setResult({
        title: '已保存问题模式',
        detail: `${ruleset} · 更新 ${String(payload.updated_count || patternEntries.length)} 条模式`,
      })
      toast.success('问题模式已保存')
      await loadRulesetDetail(ruleset)
    } catch (error) {
      toast.error(formatApiError(error, '保存问题模式失败'))
    } finally {
      setSavingPatterns(false)
    }
  }

  const saveIntents = async () => {
    const ruleset = selectedRuleset.trim()
    if (!ruleset) return
    setSavingIntents(true)
    try {
      const payload = await industryRulesApi.updateIntents(ruleset, {
        intents: buildIntentsPayload(intentEntries),
      })
      setResult({
        title: '已保存意图分类',
        detail: `${ruleset} · 更新 ${String(payload.updated_count || intentEntries.length)} 条意图`,
      })
      toast.success('意图分类已保存')
      await loadRulesetDetail(ruleset)
    } catch (error) {
      toast.error(formatApiError(error, '保存意图分类失败'))
    } finally {
      setSavingIntents(false)
    }
  }

  const exportCurrentRuleset = () => {
    const payload = {
      ruleset: selectedRuleset,
      glossary: buildGlossaryPayload(glossaryEntries),
      patterns: buildPatternsPayload(patternEntries),
      intents: buildIntentsPayload(intentEntries),
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: 'application/json;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${selectedRuleset || 'industry-rules'}.json`
    anchor.click()
    globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <PageScaffold
      title="行业规则库"
      description="术语、问题模式与意图分类是垂直 RAG 的可运营护城河。这里把 ruleset 编辑、候选审核和改写预览收敛到同一个工作台。"
      icon={ShieldCheck}
      iconColor="text-blue-600"
      badge="Ruleset CMS"
      compact={false}
      top={
        <div className="rounded-2xl border border-slate-200 bg-card p-4 shadow-[0_8px_24px_rgba(15,23,42,0.05)]">
          <div className="grid gap-3 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="industry-rules-ruleset">规则集</Label>
                <Select
                  value={selectedRuleset}
                  onValueChange={setSelectedRuleset}
                  disabled={loadingMeta || loadingRuleset}
                >
                  <SelectTrigger
                    id="industry-rules-ruleset"
                    className="h-10 rounded-xl border-slate-200 bg-card"
                  >
                    <SelectValue
                      placeholder={
                        loadingMeta ? '加载规则集中...' : '选择规则集'
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {rulesets.map((item) => (
                      <SelectItem key={item.name} value={item.name}>
                        {item.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="industry-rules-dataset">候选来源数据集</Label>
                <Select
                  value={selectedDatasetId}
                  onValueChange={setSelectedDatasetId}
                  disabled={loadingMeta}
                >
                  <SelectTrigger
                    id="industry-rules-dataset"
                    className="h-10 rounded-xl border-slate-200 bg-card"
                  >
                    <SelectValue
                      placeholder={
                        loadingMeta ? '加载数据集中...' : '选择数据集'
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {datasets.map((item) => (
                      <SelectItem key={String(item.id)} value={String(item.id)}>
                        {item.name || item.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
              <div className="text-[12px] font-medium uppercase tracking-[0.12em] text-slate-500">
                规则集概览
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant="outline">
                  术语{' '}
                  {selectedRulesetSummary?.glossary_count ??
                    glossaryEntries.length}
                </Badge>
                <Badge variant="outline">
                  模式{' '}
                  {selectedRulesetSummary?.pattern_count ??
                    patternEntries.length}
                </Badge>
                <Badge variant="outline">
                  意图{' '}
                  {selectedRulesetSummary?.intent_count ?? intentEntries.length}
                </Badge>
                <Badge variant="outline">
                  候选 {visibleGlossarySuggestions.length}
                </Badge>
                {selectedDataset ? (
                  <Badge variant="outline">
                    数据集 {selectedDataset.name || selectedDataset.id}
                  </Badge>
                ) : null}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  className="h-9 rounded-xl border-slate-200 bg-card"
                  disabled={loadingMeta || loadingRuleset}
                  onClick={refreshMeta}
                >
                  {loadingMeta ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4" />
                  )}
                  刷新
                </Button>
                <Button
                  variant="outline"
                  className="h-9 rounded-xl border-slate-200 bg-card"
                  disabled={!selectedRuleset.trim()}
                  onClick={exportCurrentRuleset}
                >
                  <ExternalLink className="h-4 w-4" />
                  导出当前规则集
                </Button>
              </div>
            </div>
          </div>
        </div>
      }
      bodyContainerClassName="max-w-[1580px]"
    >
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_360px]">
        <div className="min-w-0 rounded-2xl border border-slate-200 bg-card shadow-[0_8px_24px_rgba(15,23,42,0.05)]">
          <Tabs defaultValue="glossary">
            <div className="border-b border-slate-200 px-4">
              <TabsList className="h-12 gap-6 rounded-none bg-transparent p-0">
                <TabsTrigger
                  value="glossary"
                  className="h-12 rounded-none border-b-2 border-transparent px-0 text-[13px] data-[state=active]:border-blue-600 data-[state=active]:bg-transparent"
                >
                  术语
                </TabsTrigger>
                <TabsTrigger
                  value="patterns"
                  className="h-12 rounded-none border-b-2 border-transparent px-0 text-[13px] data-[state=active]:border-blue-600 data-[state=active]:bg-transparent"
                >
                  问题模式
                </TabsTrigger>
                <TabsTrigger
                  value="intents"
                  className="h-12 rounded-none border-b-2 border-transparent px-0 text-[13px] data-[state=active]:border-blue-600 data-[state=active]:bg-transparent"
                >
                  意图分类
                </TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="glossary" className="m-0 p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex min-w-[260px] items-center gap-2 rounded-xl border border-slate-200 bg-card px-3">
                  <Search className="h-4 w-4 text-slate-400" />
                  <Input
                    value={searchValue}
                    onChange={(event) => setSearchValue(event.target.value)}
                    placeholder="搜索术语或别名"
                    className="h-10 border-0 px-0 shadow-none focus-visible:ring-2 focus-visible:ring-ring/30"
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    className="h-9 rounded-xl border-slate-200 bg-card"
                    onClick={() =>
                      setGlossaryEntries((prev) => [
                        ...prev,
                        {
                          id: makeLocalId('glossary'),
                          term: '',
                          aliasesText: '',
                        },
                      ])
                    }
                  >
                    <Plus className="h-4 w-4" />
                    新增术语
                  </Button>
                  <Button
                    className="h-9 rounded-xl bg-slate-950 px-4 text-info-foreground hover:bg-slate-800"
                    disabled={savingGlossary}
                    onClick={() => detachPromise(saveGlossary())}
                  >
                    {savingGlossary ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4" />
                    )}
                    保存术语
                  </Button>
                </div>
              </div>

              <div className="overflow-hidden rounded-2xl border border-slate-200">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-[12px] text-slate-500">
                    <tr>
                      <th className="px-4 py-3 font-medium">Term</th>
                      <th className="px-4 py-3 font-medium">Aliases</th>
                      <th className="px-4 py-3 font-medium">来源</th>
                      <th className="px-4 py-3 font-medium text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleGlossaryEntries.map((entry) => (
                      <tr
                        key={entry.id}
                        className="border-t border-slate-200 align-top"
                      >
                        <td className="px-4 py-3">
                          <Input
                            value={entry.term}
                            onChange={(event) =>
                              setGlossaryEntry(entry.id, {
                                term: event.target.value,
                              })
                            }
                            placeholder="术语"
                            className="h-9 rounded-xl border-slate-200"
                          />
                        </td>
                        <td className="px-4 py-3">
                          <Input
                            value={entry.aliasesText}
                            onChange={(event) =>
                              setGlossaryEntry(entry.id, {
                                aliasesText: event.target.value,
                              })
                            }
                            placeholder="别名，逗号分隔"
                            className="h-9 rounded-xl border-slate-200"
                          />
                        </td>
                        <td className="px-4 py-3 text-[12px] text-slate-500">
                          规则库
                        </td>
                        <td className="px-4 py-3 text-right">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900"
                            aria-label="删除术语"
                            onClick={() =>
                              setGlossaryEntries((prev) =>
                                prev.filter((item) => item.id !== entry.id)
                              )
                            }
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </td>
                      </tr>
                    ))}
                    {!visibleGlossaryEntries.length ? (
                      <tr>
                        <td
                          colSpan={4}
                          className="px-4 py-10 text-center text-[13px] text-slate-500"
                        >
                          当前规则集还没有可展示的术语，或搜索条件为空。
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </TabsContent>

            <TabsContent value="patterns" className="m-0 p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="text-[13px] text-slate-500">
                  Marker、澄清 followup 与启用状态直接映射到 `patterns.yaml`。
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    className="h-9 rounded-xl border-slate-200 bg-card"
                    onClick={() =>
                      setPatternEntries((prev) => [
                        ...prev,
                        {
                          id: makeLocalId('pattern'),
                          markersText: '',
                          followup: '',
                          enabled: true,
                        },
                      ])
                    }
                  >
                    <Plus className="h-4 w-4" />
                    新增模式
                  </Button>
                  <Button
                    className="h-9 rounded-xl bg-slate-950 px-4 text-info-foreground hover:bg-slate-800"
                    disabled={savingPatterns}
                    onClick={() => detachPromise(savePatterns())}
                  >
                    {savingPatterns ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4" />
                    )}
                    保存模式
                  </Button>
                </div>
              </div>

              <div className="space-y-3">
                {patternEntries.map((entry) => (
                  <div
                    key={entry.id}
                    className="rounded-2xl border border-slate-200 p-4"
                  >
                    <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_120px_56px]">
                      <Input
                        value={entry.markersText}
                        onChange={(event) =>
                          setPatternEntry(entry.id, {
                            markersText: event.target.value,
                          })
                        }
                        placeholder="Marker，逗号分隔"
                        className="h-10 rounded-xl border-slate-200"
                      />
                      <Input
                        value={entry.followup}
                        onChange={(event) =>
                          setPatternEntry(entry.id, {
                            followup: event.target.value,
                          })
                        }
                        placeholder="澄清话术 / followup"
                        className="h-10 rounded-xl border-slate-200"
                      />
                      <label className="flex items-center gap-2 rounded-xl border border-slate-200 px-3 text-sm text-slate-600">
                        <Checkbox
                          checked={entry.enabled}
                          onCheckedChange={(value) =>
                            setPatternEntry(entry.id, {
                              enabled: value === true,
                            })
                          }
                        />
                        启用
                      </label>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-10 w-10 rounded-xl text-slate-500 hover:bg-slate-100 hover:text-slate-900"
                        aria-label="删除问题模式"
                        onClick={() =>
                          setPatternEntries((prev) =>
                            prev.filter((item) => item.id !== entry.id)
                          )
                        }
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                ))}
                {!patternEntries.length ? (
                  <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-10 text-center text-[13px] text-slate-500">
                    当前规则集没有问题模式。
                  </div>
                ) : null}
              </div>
            </TabsContent>

            <TabsContent value="intents" className="m-0 p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="text-[13px] text-slate-500">
                  Intent 名称、关键词与路由策略直接映射到 `intents.yaml`。
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    className="h-9 rounded-xl border-slate-200 bg-card"
                    onClick={() =>
                      setIntentEntries((prev) => [
                        ...prev,
                        {
                          id: makeLocalId('intent'),
                          name: '',
                          keywordsText: '',
                          route: 'default',
                        },
                      ])
                    }
                  >
                    <Plus className="h-4 w-4" />
                    新增意图
                  </Button>
                  <Button
                    className="h-9 rounded-xl bg-slate-950 px-4 text-info-foreground hover:bg-slate-800"
                    disabled={savingIntents}
                    onClick={() => detachPromise(saveIntents())}
                  >
                    {savingIntents ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4" />
                    )}
                    保存意图
                  </Button>
                </div>
              </div>

              <div className="space-y-3">
                {intentEntries.map((entry) => (
                  <div
                    key={entry.id}
                    className="rounded-2xl border border-slate-200 p-4"
                  >
                    <div className="grid gap-3 lg:grid-cols-[180px_minmax(0,1fr)_180px_56px]">
                      <Input
                        value={entry.name}
                        onChange={(event) =>
                          setIntentEntry(entry.id, { name: event.target.value })
                        }
                        placeholder="Intent 名称"
                        className="h-10 rounded-xl border-slate-200"
                      />
                      <Input
                        value={entry.keywordsText}
                        onChange={(event) =>
                          setIntentEntry(entry.id, {
                            keywordsText: event.target.value,
                          })
                        }
                        placeholder="Keywords，逗号分隔"
                        className="h-10 rounded-xl border-slate-200"
                      />
                      <Input
                        value={entry.route}
                        onChange={(event) =>
                          setIntentEntry(entry.id, {
                            route: event.target.value,
                          })
                        }
                        placeholder="route"
                        className="h-10 rounded-xl border-slate-200"
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-10 w-10 rounded-xl text-slate-500 hover:bg-slate-100 hover:text-slate-900"
                        aria-label="删除意图"
                        onClick={() =>
                          setIntentEntries((prev) =>
                            prev.filter((item) => item.id !== entry.id)
                          )
                        }
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                ))}
                {!intentEntries.length ? (
                  <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-10 text-center text-[13px] text-slate-500">
                    当前规则集没有意图分类。
                  </div>
                ) : null}
              </div>
            </TabsContent>
          </Tabs>
        </div>

        <aside className="space-y-4">
          <div className="rounded-2xl border border-slate-200 bg-card p-4 shadow-[0_8px_24px_rgba(15,23,42,0.05)]">
            <div className="flex items-center gap-2 text-[15px] font-semibold text-slate-950">
              <Sparkles className="h-4 w-4 text-blue-600" />
              改写预览
            </div>
            <p className="mt-1 text-[12px] leading-5 text-slate-500">
              使用当前已保存的 ruleset 调
              `preview-rewrite`。未保存的本地编辑不会反映到这里。
            </p>
            <div className="mt-3 space-y-2">
              <Label htmlFor="industry-rules-preview-query">输入 Query</Label>
              <Input
                id="industry-rules-preview-query"
                value={previewQuery}
                onChange={(event) => setPreviewQuery(event.target.value)}
                placeholder="输入要测试的 query…"
                className="h-10 rounded-xl border-slate-200"
              />
            </div>
            <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
              {previewing ? (
                <div className="flex items-center gap-2 text-[13px] text-slate-500">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  正在计算改写预览…
                </div>
              ) : preview ? (
                <div className="space-y-3 text-[13px]">
                  <div>
                    <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">
                      Input
                    </div>
                    <div className="mt-1 text-slate-900">
                      {preview.originalQuery}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">
                      Output
                    </div>
                    <div className="mt-1 rounded-xl border border-blue-100 bg-card px-3 py-2 text-slate-900">
                      {preview.expandedQuery}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge
                      variant="outline"
                      className={cn(
                        preview.changed
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                          : 'border-slate-200 bg-card text-slate-600'
                      )}
                    >
                      {preview.changed ? '已命中规则并改写' : '未触发改写'}
                    </Badge>
                    <Badge variant="outline">
                      Ruleset {selectedRuleset || '-'}
                    </Badge>
                  </div>
                </div>
              ) : (
                <div className="text-[13px] text-slate-500">
                  输入 query 后这里会展示改写结果。
                </div>
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-card p-4 shadow-[0_8px_24px_rgba(15,23,42,0.05)]">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-[15px] font-semibold text-slate-950">
                <Database className="h-4 w-4 text-blue-600" />
                规则候选（待审核）
              </div>
              <Button
                variant="outline"
                className="h-8 rounded-lg border-slate-200 bg-card px-2.5 text-[12px]"
                disabled={
                  !selectedDatasetId.trim() ||
                  !selectedRuleset.trim() ||
                  loadingSuggestions
                }
                onClick={() =>
                  detachPromise(
                    loadGlossarySuggestions(selectedDatasetId, selectedRuleset)
                  )
                }
              >
                {loadingSuggestions ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                刷新
              </Button>
            </div>
            <p className="mt-1 text-[12px] leading-5 text-slate-500">
              选择数据集查看术语挖掘候选。接受会先进入当前规则表，再由“保存术语”统一落库。
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge variant="outline">规则集 {selectedRuleset || '-'}</Badge>
              <Badge variant="outline">
                数据集 {selectedDataset?.name || selectedDataset?.id || '-'}
              </Badge>
              <Badge variant="outline">
                候选 {visibleGlossarySuggestions.length}
              </Badge>
            </div>
            <div className="mt-3 flex items-center justify-between gap-2">
              <div className="text-[12px] text-slate-500">
                已选 {selectedSuggestionCount} 条
              </div>
              <Button
                variant="outline"
                className="h-8 rounded-lg border-slate-200 bg-card px-2.5 text-[12px]"
                disabled={!selectedSuggestionCount}
                onClick={acceptSelectedSuggestions}
              >
                <Check className="h-3.5 w-3.5" />
                批量接受
              </Button>
            </div>
            <div className="mt-3 max-h-[520px] space-y-2 overflow-auto pr-1">
              {visibleGlossarySuggestions.map((entry) => (
                <div
                  key={entry.token}
                  className="rounded-xl border border-slate-200 p-3"
                >
                  <div className="flex items-start gap-2">
                    <Checkbox
                      checked={selectedSuggestionTokens[entry.token] === true}
                      onCheckedChange={(value) =>
                        setSelectedSuggestionTokens((prev) => ({
                          ...prev,
                          [entry.token]: value === true,
                        }))
                      }
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <div className="truncate text-[13px] font-semibold text-slate-950">
                          {entry.token}
                        </div>
                        <Badge variant="outline">{entry.count} 次</Badge>
                      </div>
                      <div className="mt-1 text-[11px] text-slate-500">
                        source: {entry.source}
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 flex gap-2">
                    <Button
                      variant="outline"
                      className="h-8 flex-1 rounded-lg border-slate-200 bg-card px-2.5 text-[12px]"
                      onClick={() => addGlossarySuggestion(entry.token)}
                    >
                      <Check className="h-3.5 w-3.5" />
                      接受
                    </Button>
                    <Button
                      variant="ghost"
                      className="h-8 rounded-lg px-2.5 text-[12px] text-slate-500 hover:bg-slate-100 hover:text-slate-900"
                      onClick={() =>
                        setDismissedSuggestionTokens((prev) => ({
                          ...prev,
                          [entry.token]: true,
                        }))
                      }
                    >
                      <X className="h-3.5 w-3.5" />
                      拒绝
                    </Button>
                  </div>
                </div>
              ))}
              {!visibleGlossarySuggestions.length ? (
                <div className="rounded-2xl border border-dashed border-slate-200 px-4 py-10 text-center text-[13px] text-slate-500">
                  当前数据集暂无新的术语候选，或候选已被处理。
                </div>
              ) : null}
            </div>
          </div>

          {result ? (
            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 text-[13px]">
              <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">
                最近操作
              </div>
              <div className="mt-2 font-semibold text-slate-950">
                {result.title}
              </div>
              <div className="mt-1 text-slate-500">{result.detail}</div>
            </div>
          ) : null}
        </aside>
      </div>
    </PageScaffold>
  )
}
