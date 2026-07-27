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
import { randomBase36Id } from '@/lib/secure-random'
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
    seed?.trim() || `${Date.now()}-${randomBase36Id(6)}`
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

const WORKBENCH_PANEL =
  'rounded-[14px] border border-border/60 bg-card/90 shadow-[0_10px_28px_rgba(15,23,42,0.045)]'
const DENSE_FIELD =
  'h-9 rounded-lg border-border bg-card text-[13px] font-medium text-foreground shadow-none focus-visible:ring-primary/20'
const DENSE_BUTTON =
  'h-8 rounded-lg border-border bg-card px-2.5 text-[12px] font-semibold text-foreground/85 hover:bg-primary/10 hover:text-primary'

export function IndustryRulesWorkbench() {
  const [selectedRuleset, setSelectedRuleset] = useState('')
  const [selectedDatasetId, setSelectedDatasetId] = useState('')
  const [searchValue, setSearchValue] = useState('')
  const [previewQuery, setPreviewQuery] = useState('授权报错怎么办')

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
    queryKey: queryKeys.datasets.exhaustive({ purpose: 'industry-rules' }),
    queryFn: () => datasetApi.listAll(),
  })
  const rulesetDetailQuery = useQuery({
    queryKey: queryKeys.industryRules.ruleset(selectedRuleset),
    enabled: Boolean(selectedRuleset.trim()),
    queryFn: () => industryRulesApi.getRuleset(selectedRuleset.trim()),
  })
  const glossarySuggestionsQuery = useQuery({
    queryKey: queryKeys.industryRules.glossarySuggestions(
      selectedDatasetId,
      selectedRuleset,
      { limit: 20 }
    ),
    enabled: Boolean(selectedDatasetId.trim() && selectedRuleset.trim()),
    queryFn: () =>
      datasetApi.getAnalysisRuleSuggestions(selectedDatasetId.trim(), {
        ruleset: selectedRuleset.trim(),
        limit: 20,
      }),
  })

  const rulesets = useMemo(
    () => rulesetsQuery.data?.rulesets || [],
    [rulesetsQuery.data?.rulesets]
  )
  const datasets = useMemo(
    () => datasetsQuery.data || [],
    [datasetsQuery.data]
  )
  const loadingMeta = rulesetsQuery.isFetching || datasetsQuery.isFetching
  const metaError = rulesetsQuery.error || datasetsQuery.error
  const loadingRuleset = rulesetDetailQuery.isFetching
  const loadingSuggestions = glossarySuggestionsQuery.isFetching

  const refreshMeta = () => {
    rulesetsQuery.refetch()
    datasetsQuery.refetch()
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
    if (!rulesetDetailQuery.error) return
    toast.error(formatApiError(rulesetDetailQuery.error, '加载规则详情失败'))
  }, [rulesetDetailQuery.error])

  useEffect(() => {
    if (!glossarySuggestionsQuery.error) return
    toast.error(formatApiError(glossarySuggestionsQuery.error, '加载规则候选失败'))
  }, [glossarySuggestionsQuery.error])

  useEffect(() => {
    if (!selectedRuleset && rulesets[0]?.name)
      setSelectedRuleset(rulesets[0].name)
  }, [rulesets, selectedRuleset])

  useEffect(() => {
    if (!selectedDatasetId && datasets[0]?.id)
      setSelectedDatasetId(String(datasets[0].id))
  }, [datasets, selectedDatasetId])

  useEffect(() => {
    if (!rulesetDetailQuery.data?.ruleset) return
    setGlossaryEntries(glossaryEntriesFromDetail(rulesetDetailQuery.data.ruleset))
    setPatternEntries(patternEntriesFromDetail(rulesetDetailQuery.data.ruleset))
    setIntentEntries(intentEntriesFromDetail(rulesetDetailQuery.data.ruleset))
  }, [rulesetDetailQuery.data])

  useEffect(() => {
    if (!glossarySuggestionsQuery.data) return
    setGlossarySuggestions(suggestionRowsFromPayload(glossarySuggestionsQuery.data))
    setSelectedSuggestionTokens({})
    setDismissedSuggestionTokens({})
  }, [glossarySuggestionsQuery.data])

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
      await rulesetDetailQuery.refetch()
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
      await rulesetDetailQuery.refetch()
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
      await rulesetDetailQuery.refetch()
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
      title=""
      showHeader={false}
      compact={false}
      size="full"
      top={
        <div className="space-y-3">
          <div className="relative flex min-h-[150px] items-center overflow-hidden rounded-[16px] border border-primary/20 bg-[linear-gradient(105deg,hsl(var(--card))_0%,hsl(var(--card)/0.94)_45%,hsl(var(--info)/0.14)_100%)] px-5 py-5 shadow-[0_14px_36px_rgba(15,23,42,0.06)]">
            <div className="pointer-events-none absolute inset-y-0 right-0 hidden w-[460px] overflow-hidden lg:block">
              <div className="absolute right-[-80px] top-[-80px] h-[260px] w-[430px] rotate-[-16deg] rounded-[42px] border border-border/70 bg-card/35" />
              <div className="absolute right-[48px] top-[22px] h-[118px] w-[210px] rotate-[-16deg] rounded-[30px] bg-primary/10 shadow-[0_18px_42px_hsl(var(--primary)/0.18)]" />
              <div className="absolute right-[132px] top-[24px] flex h-[84px] w-[96px] rotate-[-16deg] items-center justify-center rounded-[24px] border border-primary/30 bg-card/85 shadow-[0_18px_32px_hsl(var(--primary)/0.2)]">
                <ShieldCheck className="h-11 w-11 rotate-[16deg] text-primary" />
              </div>
            </div>
            <div className="relative flex max-w-[760px] items-center gap-4">
              <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-[16px] border border-primary/20 bg-primary/5 text-primary shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]">
                <ShieldCheck className="h-8 w-8" />
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-[30px] font-semibold leading-tight tracking-[-0.035em] text-foreground">
                    行业规则库
                  </h1>
                  <span className="rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
                    Ruleset CMS
                  </span>
                </div>
                <p className="mt-2 max-w-[640px] text-[13px] font-medium leading-6 text-muted-foreground">
                  维护术语、问题模式和意图分类，先预览查询改写效果，再把候选规则审核入库。
                </p>
              </div>
            </div>
          </div>

          <div className={cn(WORKBENCH_PANEL, 'flex min-h-[150px] items-center p-4')}>
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_1px_minmax(360px,0.82fr)]">
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="industry-rules-ruleset" className="text-[12px] font-semibold text-foreground/85">
                    规则集
                  </Label>
                  <Select
                    value={selectedRuleset}
                    onValueChange={setSelectedRuleset}
                    disabled={loadingMeta || loadingRuleset}
                  >
                    <SelectTrigger
                      id="industry-rules-ruleset"
                      className={DENSE_FIELD}
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
                  <Label htmlFor="industry-rules-dataset" className="text-[12px] font-semibold text-foreground/85">
                    候选来源数据集
                  </Label>
                  <Select
                    value={selectedDatasetId}
                    onValueChange={setSelectedDatasetId}
                    disabled={loadingMeta}
                  >
                    <SelectTrigger
                      id="industry-rules-dataset"
                      className={DENSE_FIELD}
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

              <div className="hidden bg-border/70 xl:block" />

              <div className="space-y-3">
                <div className="text-[12px] font-semibold text-foreground">
                  规则集概览
                </div>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline" className="bg-card font-semibold">
                    术语{' '}
                    {selectedRulesetSummary?.glossary_count ??
                      glossaryEntries.length}
                  </Badge>
                  <Badge variant="outline" className="bg-card font-semibold">
                    模式{' '}
                    {selectedRulesetSummary?.pattern_count ??
                      patternEntries.length}
                  </Badge>
                  <Badge variant="outline" className="bg-card font-semibold">
                    意图{' '}
                    {selectedRulesetSummary?.intent_count ?? intentEntries.length}
                  </Badge>
                  <Badge variant="outline" className="bg-card font-semibold">
                    候选 {visibleGlossarySuggestions.length}
                  </Badge>
                  {selectedDataset ? (
                    <Badge variant="outline" className="bg-card font-semibold">
                      数据集 {selectedDataset.name || selectedDataset.id}
                    </Badge>
                  ) : null}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    className={DENSE_BUTTON}
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
                    className={DENSE_BUTTON}
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
        </div>
      }
      topClassName="pt-4 md:pt-5 [&>div]:max-w-[1580px]"
      bodyContainerClassName="max-w-[1580px]"
      bodyClassName="pt-0"
    >
      <div className="grid items-stretch gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div
          className={cn(
            WORKBENCH_PANEL,
            'flex min-h-[calc(100vh-410px)] min-w-0 flex-col overflow-hidden'
          )}
        >
          <Tabs defaultValue="glossary" className="flex h-full flex-col">
            <div className="border-b border-border px-4">
              <TabsList className="h-11 gap-6 rounded-none bg-transparent p-0">
                <TabsTrigger
                  value="glossary"
                  className="h-11 rounded-none border-b-2 border-transparent px-0 text-[13px] font-semibold data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary"
                >
                  术语
                </TabsTrigger>
                <TabsTrigger
                  value="patterns"
                  className="h-11 rounded-none border-b-2 border-transparent px-0 text-[13px] font-semibold data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary"
                >
                  问题模式
                </TabsTrigger>
                <TabsTrigger
                  value="intents"
                  className="h-11 rounded-none border-b-2 border-transparent px-0 text-[13px] font-semibold data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary"
                >
                  意图分类
                </TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="glossary" className="m-0 flex flex-1 flex-col p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex min-w-[260px] items-center gap-2 rounded-lg border border-border bg-card px-3">
                  <Search className="h-4 w-4 text-muted-foreground" />
                  <Input
                    value={searchValue}
                    onChange={(event) => setSearchValue(event.target.value)}
                    placeholder="搜索术语或别名"
                    className="h-9 border-0 px-0 text-[13px] font-medium shadow-none focus-visible:ring-2 focus-visible:ring-primary/20"
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    className={DENSE_BUTTON}
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
                    className="h-8 rounded-lg bg-primary px-3 text-[12px] font-semibold text-primary-foreground hover:bg-primary"
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

              <div className="flex-1 overflow-hidden rounded-[12px] border border-border">
                <table className="w-full text-left text-sm">
                  <thead className="bg-muted/50 text-[12px] font-semibold text-muted-foreground">
                    <tr>
                      <th className="px-4 py-3">术语</th>
                      <th className="px-4 py-3">别名</th>
                      <th className="px-4 py-3">来源</th>
                      <th className="px-4 py-3 text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleGlossaryEntries.map((entry) => (
                      <tr
                        key={entry.id}
                        className="border-t border-border align-top"
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
                            className={DENSE_FIELD}
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
                            className={DENSE_FIELD}
                          />
                        </td>
                        <td className="px-4 py-3 text-[12px] font-medium text-muted-foreground">
                          规则库
                        </td>
                        <td className="px-4 py-3 text-right">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
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
                    {visibleGlossaryEntries.length ? null : (
                      <tr>
                        <td
                          colSpan={4}
                          className="px-4 py-10 text-center text-[13px] text-muted-foreground"
                        >
                          当前规则集还没有可展示的术语，或搜索条件为空。
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </TabsContent>

            <TabsContent value="patterns" className="m-0 flex flex-1 flex-col p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="text-[13px] font-medium text-muted-foreground">
                  维护触发词、澄清话术与启用状态。
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    className={DENSE_BUTTON}
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
                    className="h-8 rounded-lg bg-primary px-3 text-[12px] font-semibold text-primary-foreground hover:bg-primary"
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
                    className="rounded-[12px] border border-border bg-card p-3"
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
                        className={DENSE_FIELD}
                      />
                      <Input
                        value={entry.followup}
                        onChange={(event) =>
                          setPatternEntry(entry.id, {
                            followup: event.target.value,
                          })
                        }
                        placeholder="澄清话术"
                        className={DENSE_FIELD}
                      />
                      <label className="flex items-center gap-2 rounded-lg border border-border px-3 text-[13px] font-medium text-muted-foreground">
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
                        className="h-9 w-9 rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
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
                    {patternEntries.length ? null : (
                      <div className="rounded-2xl border border-dashed border-border px-4 py-10 text-center text-[13px] text-muted-foreground">
                        当前规则集没有问题模式。
                      </div>
                    )}
              </div>
            </TabsContent>

            <TabsContent value="intents" className="m-0 flex flex-1 flex-col p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="text-[13px] font-medium text-muted-foreground">
                  维护意图名称、关键词与路由策略。
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    className={DENSE_BUTTON}
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
                    className="h-8 rounded-lg bg-primary px-3 text-[12px] font-semibold text-primary-foreground hover:bg-primary"
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
                    className="rounded-[12px] border border-border bg-card p-3"
                  >
                    <div className="grid gap-3 lg:grid-cols-[180px_minmax(0,1fr)_180px_56px]">
                      <Input
                        value={entry.name}
                        onChange={(event) =>
                          setIntentEntry(entry.id, { name: event.target.value })
                        }
                        placeholder="意图名称"
                        className={DENSE_FIELD}
                      />
                      <Input
                        value={entry.keywordsText}
                        onChange={(event) =>
                          setIntentEntry(entry.id, {
                            keywordsText: event.target.value,
                          })
                        }
                        placeholder="关键词，逗号分隔"
                        className={DENSE_FIELD}
                      />
                      <Input
                        value={entry.route}
                        onChange={(event) =>
                          setIntentEntry(entry.id, {
                            route: event.target.value,
                          })
                        }
                        placeholder="路由"
                        className={DENSE_FIELD}
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-9 w-9 rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
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
                {intentEntries.length ? null : (
                  <div className="rounded-2xl border border-dashed border-border px-4 py-10 text-center text-[13px] text-muted-foreground">
                    当前规则集没有意图分类。
                  </div>
                )}
              </div>
            </TabsContent>
          </Tabs>
        </div>

        <aside className="flex h-full flex-col gap-4">
          <div className={cn(WORKBENCH_PANEL, 'flex-1 p-4')}>
            <div className="flex items-center gap-2 text-[15px] font-semibold text-foreground">
              <Sparkles className="h-4 w-4 text-primary" />
              改写预览
            </div>
            <p className="mt-1 text-[12px] font-medium leading-5 text-muted-foreground">
              使用已保存规则测试问题改写；未保存的本地编辑不会参与预览。
            </p>
            <div className="mt-3 space-y-2">
              <Label htmlFor="industry-rules-preview-query" className="text-[12px] font-semibold text-foreground/85">
                输入问题
              </Label>
              <Input
                id="industry-rules-preview-query"
                value={previewQuery}
                onChange={(event) => setPreviewQuery(event.target.value)}
                placeholder="输入要测试的问题"
                className={DENSE_FIELD}
              />
            </div>
            <div className="mt-4 rounded-[12px] border border-border bg-muted/40 p-3">
              {previewing ? (
                <div className="flex items-center gap-2 text-[13px] font-medium text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  正在计算改写预览…
                </div>
              ) : preview ? (
                <div className="space-y-3 text-[13px]">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                      输入
                    </div>
                    <div className="mt-1 font-medium text-foreground">
                      {preview.originalQuery}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                      输出
                    </div>
                    <div className="mt-1 rounded-lg border border-primary/20 bg-card px-3 py-2 font-medium text-foreground">
                      {preview.expandedQuery}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge
                      variant="outline"
                      className={cn(
                        preview.changed
                          ? 'border-success/30 bg-success/10 text-success'
                          : 'border-border bg-card text-muted-foreground'
                      )}
                    >
                      {preview.changed ? '已命中规则并改写' : '未触发改写'}
                    </Badge>
                    <Badge variant="outline">
                      规则集 {selectedRuleset || '-'}
                    </Badge>
                  </div>
                </div>
              ) : (
                <div className="text-[13px] font-medium text-muted-foreground">
                  输入问题后这里会展示改写结果。
                </div>
              )}
            </div>
          </div>

          <div className={cn(WORKBENCH_PANEL, 'p-4')}>
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-[15px] font-semibold text-foreground">
                <Database className="h-4 w-4 text-primary" />
                规则候选（待审核）
              </div>
              <Button
                variant="outline"
                className={DENSE_BUTTON}
                disabled={
                  !selectedDatasetId.trim() ||
                  !selectedRuleset.trim() ||
                  loadingSuggestions
                }
                onClick={() =>
                  detachPromise(
                    glossarySuggestionsQuery.refetch()
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
            <p className="mt-1 text-[12px] font-medium leading-5 text-muted-foreground">
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
              <div className="text-[12px] font-medium text-muted-foreground">
                已选 {selectedSuggestionCount} 条
              </div>
              <Button
                variant="outline"
                className={DENSE_BUTTON}
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
                  className="rounded-[12px] border border-border bg-card p-3"
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
                        <div className="truncate text-[13px] font-semibold text-foreground">
                          {entry.token}
                        </div>
                        <Badge variant="outline">{entry.count} 次</Badge>
                      </div>
                      <div className="mt-1 text-[11px] font-medium text-muted-foreground">
                        来源：{entry.source}
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 flex gap-2">
                    <Button
                      variant="outline"
                      className="h-8 flex-1 rounded-lg border-border bg-card px-2.5 text-[12px] font-semibold hover:bg-primary/10 hover:text-primary"
                      onClick={() => addGlossarySuggestion(entry.token)}
                    >
                      <Check className="h-3.5 w-3.5" />
                      接受
                    </Button>
                    <Button
                      variant="ghost"
                      className="h-8 rounded-lg px-2.5 text-[12px] font-semibold text-muted-foreground hover:bg-muted hover:text-foreground"
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
              {visibleGlossarySuggestions.length ? null : (
                <div className="rounded-[12px] border border-dashed border-border px-4 py-10 text-center text-[13px] font-medium text-muted-foreground">
                  当前数据集暂无新的术语候选，或候选已被处理。
                </div>
              )}
            </div>
          </div>

          {result ? (
            <div className="rounded-[12px] border border-border bg-muted/40 p-4 text-[13px]">
              <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                最近操作
              </div>
              <div className="mt-2 font-semibold text-foreground">
                {result.title}
              </div>
              <div className="mt-1 font-medium text-muted-foreground">{result.detail}</div>
            </div>
          ) : null}
        </aside>
      </div>
    </PageScaffold>
  )
}
