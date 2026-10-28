'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
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
} from '@/components/icons'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { OperationalWorkspace, WorkspaceTableScroll, WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
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

export function IndustryRulesWorkbench() {
  const [selectedRuleset, setSelectedRuleset] = useState('')
  const [selectedDatasetId, setSelectedDatasetId] = useState('')
  const [searchValue, setSearchValue] = useState('')
  const [previewQuery, setPreviewQuery] = useState('')
  const [tool, setTool] = useState<'preview' | 'suggestions' | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [operationError, setOperationError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState('glossary')
  const previewSequence = useRef(0)
  const [editor, setEditor] = useState<{ kind: 'glossary'; value: GlossaryEntry } | { kind: 'patterns'; value: PatternEntry } | { kind: 'intents'; value: IntentEntry } | null>(null)

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

  const runPreview = async (query: string, rulesetName: string, sequence: number) => {
    const q = query.trim()
    const ruleset = rulesetName.trim()
    if (!q || !ruleset) {
      setPreview(null)
      return
    }
    setPreviewing(true)
    setPreviewError(null)
    try {
      const payload = await industryRulesApi.previewRewrite({
        ruleset,
        query: q,
      })
      if (previewSequence.current !== sequence) return
      setPreview({
        originalQuery: payload.original_query,
        expandedQuery: payload.expanded_query,
        changed: payload.changed,
      })
    } catch (error) {
      if (previewSequence.current === sequence) setPreviewError(formatApiError(error, '改写预览失败'))
    } finally {
      if (previewSequence.current === sequence) setPreviewing(false)
    }
  }

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
    const sequence = ++previewSequence.current
    setPreview(null); setPreviewError(null); setPreviewing(false)
    if (tool !== 'preview' || !selectedRuleset.trim() || !previewQuery.trim()) return
    const timer = window.setTimeout(() => { detachPromise(runPreview(previewQuery, selectedRuleset, sequence)) }, 280)
    return () => window.clearTimeout(timer)
  }, [previewQuery, selectedRuleset, tool])

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
    setOperationError(null)
    try {
      await industryRulesApi.updateGlossary(ruleset, {
        glossary: buildGlossaryPayload(glossaryEntries),
      })
      toast.success('术语已保存')
      await rulesetDetailQuery.refetch()
    } catch (error) {
      setOperationError(formatApiError(error, '保存术语失败'))
    } finally {
      setSavingGlossary(false)
    }
  }

  const savePatterns = async () => {
    const ruleset = selectedRuleset.trim()
    if (!ruleset) return
    setSavingPatterns(true)
    setOperationError(null)
    try {
      await industryRulesApi.updatePatterns(ruleset, {
        patterns: buildPatternsPayload(patternEntries),
      })
      toast.success('问题模式已保存')
      await rulesetDetailQuery.refetch()
    } catch (error) {
      setOperationError(formatApiError(error, '保存问题模式失败'))
    } finally {
      setSavingPatterns(false)
    }
  }

  const saveIntents = async () => {
    const ruleset = selectedRuleset.trim()
    if (!ruleset) return
    setSavingIntents(true)
    setOperationError(null)
    try {
      await industryRulesApi.updateIntents(ruleset, {
        intents: buildIntentsPayload(intentEntries),
      })
      toast.success('意图分类已保存')
      await rulesetDetailQuery.refetch()
    } catch (error) {
      setOperationError(formatApiError(error, '保存意图分类失败'))
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

  const busy = savingGlossary || savingPatterns || savingIntents
  const commitEditor = () => {
    if (!editor) return
    if (editor.kind === 'glossary') { const value = editor.value; setGlossaryEntries(prev => prev.some(item => item.id === value.id) ? prev.map(item => item.id === value.id ? value : item) : [...prev, value]) }
    if (editor.kind === 'patterns') { const value = editor.value; setPatternEntries(prev => prev.some(item => item.id === value.id) ? prev.map(item => item.id === value.id ? value : item) : [...prev, value]) }
    if (editor.kind === 'intents') { const value = editor.value; setIntentEntries(prev => prev.some(item => item.id === value.id) ? prev.map(item => item.id === value.id ? value : item) : [...prev, value]) }
    setEditor(null)
  }
  const addEntry = () => {
    if (activeTab === 'glossary') setEditor({ kind: 'glossary', value: { id: makeLocalId('glossary'), term: '', aliasesText: '' } })
    else if (activeTab === 'patterns') setEditor({ kind: 'patterns', value: { id: makeLocalId('pattern'), markersText: '', followup: '', enabled: true } })
    else setEditor({ kind: 'intents', value: { id: makeLocalId('intent'), name: '', keywordsText: '', route: 'default' } })
  }
  const saveCurrent = () => { if (activeTab === 'glossary') void saveGlossary(); else if (activeTab === 'patterns') void savePatterns(); else void saveIntents() }
  const emptyRow = <tr><td colSpan={4}><div className={ws.empty}>{searchValue ? '没有匹配的规则' : '当前规则集暂无此类规则'}</div></td></tr>
  return <OperationalWorkspace title="行业规则" icon="governance-config" context={selectedRuleset || '未选择规则集'} actions={<><Button variant="outline" disabled={!selectedRuleset} onClick={() => setTool('preview')}>查询预览</Button><Button variant="outline" onClick={() => setTool('suggestions')}>规则候选</Button><Button variant="ghost" aria-label="导出当前规则集" disabled={!selectedRuleset} onClick={exportCurrentRuleset}><ExternalLink /></Button></>} toolbar={<><Label htmlFor="industry-rules-ruleset">规则集</Label><Select value={selectedRuleset} disabled={loadingMeta || busy || !!editor} onValueChange={value => { setSelectedRuleset(value); setGlossaryEntries([]); setPatternEntries([]); setIntentEntries([]); setGlossarySuggestions([]); setSelectedSuggestionTokens({}); setOperationError(null) }}><SelectTrigger id="industry-rules-ruleset" className="w-64 max-w-full"><SelectValue placeholder="选择规则集" /></SelectTrigger><SelectContent>{rulesets.map(item => <SelectItem key={item.name} value={item.name}>{item.name}</SelectItem>)}</SelectContent></Select><Button variant="ghost" aria-label="重新读取规则目录" disabled={loadingMeta || busy} onClick={refreshMeta}><RefreshCw /></Button></>}>
    {metaError ? <WorkspaceNotice retry={refreshMeta}>{formatApiError(metaError, '加载规则集或数据集失败')}</WorkspaceNotice> : null}
    {rulesetDetailQuery.isError ? <WorkspaceNotice retry={() => { void rulesetDetailQuery.refetch() }}>{formatApiError(rulesetDetailQuery.error, '加载规则详情失败')}</WorkspaceNotice> : null}
    {operationError ? <WorkspaceNotice>{operationError}</WorkspaceNotice> : null}
    <Tabs value={activeTab} onValueChange={setActiveTab}><TabsList className={ws.tabList}><TabsTrigger value="glossary">术语 {glossaryEntries.length}</TabsTrigger><TabsTrigger value="patterns">问题模式 {patternEntries.length}</TabsTrigger><TabsTrigger value="intents">意图分类 {intentEntries.length}</TabsTrigger></TabsList>
      <div className="my-5 flex flex-wrap items-center justify-between gap-3"><Input className="w-72 max-w-full" aria-label="搜索行业规则" placeholder="搜索规则内容" value={searchValue} onChange={event => setSearchValue(event.target.value)} /><div className="flex gap-2"><Button variant="outline" onClick={addEntry} disabled={!selectedRuleset || loadingRuleset || busy}><Plus />{activeTab === 'glossary' ? '新增术语' : activeTab === 'patterns' ? '新增模式' : '新增意图'}</Button><Button disabled={!selectedRuleset || loadingRuleset || busy || rulesetDetailQuery.isError} onClick={saveCurrent}>{busy ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Save />}{activeTab === 'glossary' ? '保存术语' : activeTab === 'patterns' ? '保存模式' : '保存意图'}</Button></div></div>
      {loadingRuleset ? <p role="status" className={ws.empty}>正在读取规则…</p> : <>
        <TabsContent value="glossary" className={ws.tabContent}><WorkspaceTableScroll label="术语管理表格" stickyActions><table className={cn(ws.table, 'min-w-[580px]')}><thead><tr><th>术语</th><th>别名</th><th>来源</th><th>操作</th></tr></thead><tbody>{visibleGlossaryEntries.map(entry => <tr key={entry.id}><td className="font-medium">{entry.term || '未填写术语'}</td><td>{entry.aliasesText || '—'}</td><td>规则库</td><td><div className="flex gap-2"><Button variant="ghost" onClick={() => setEditor({ kind: 'glossary', value: { ...entry } })}>编辑</Button><Button variant="ghost" aria-label={`删除术语 ${entry.term}`} disabled={busy} onClick={() => setGlossaryEntries(prev => prev.filter(item => item.id !== entry.id))}><Trash2 /></Button></div></td></tr>)}{!visibleGlossaryEntries.length ? emptyRow : null}</tbody></table></WorkspaceTableScroll></TabsContent>
        <TabsContent value="patterns" className={ws.tabContent}><WorkspaceTableScroll label="问题模式表格" stickyActions><table className={cn(ws.table, 'min-w-[660px]')}><thead><tr><th>触发词</th><th>澄清话术</th><th>状态</th><th>操作</th></tr></thead><tbody>{patternEntries.filter(entry => `${entry.markersText} ${entry.followup}`.toLowerCase().includes(searchValue.toLowerCase())).map(entry => <tr key={entry.id}><td className="font-medium">{entry.markersText || '未填写触发词'}</td><td>{entry.followup || '—'}</td><td><Badge variant={entry.enabled ? 'soft' : 'outline'}>{entry.enabled ? '启用' : '停用'}</Badge></td><td><div className="flex gap-2"><Button variant="ghost" onClick={() => setEditor({ kind: 'patterns', value: { ...entry } })}>编辑</Button><Button variant="ghost" aria-label="删除问题模式" disabled={busy} onClick={() => setPatternEntries(prev => prev.filter(item => item.id !== entry.id))}><Trash2 /></Button></div></td></tr>)}{!patternEntries.length ? emptyRow : null}</tbody></table></WorkspaceTableScroll></TabsContent>
        <TabsContent value="intents" className={ws.tabContent}><WorkspaceTableScroll label="意图分类表格" stickyActions><table className={cn(ws.table, 'min-w-[660px]')}><thead><tr><th>意图名称</th><th>关键词</th><th>检索路由</th><th>操作</th></tr></thead><tbody>{intentEntries.filter(entry => `${entry.name} ${entry.keywordsText} ${entry.route}`.toLowerCase().includes(searchValue.toLowerCase())).map(entry => <tr key={entry.id}><td className="font-medium">{entry.name || '未填写意图'}</td><td>{entry.keywordsText || '—'}</td><td>{entry.route}</td><td><div className="flex gap-2"><Button variant="ghost" onClick={() => setEditor({ kind: 'intents', value: { ...entry } })}>编辑</Button><Button variant="ghost" aria-label={`删除意图 ${entry.name}`} disabled={busy} onClick={() => setIntentEntries(prev => prev.filter(item => item.id !== entry.id))}><Trash2 /></Button></div></td></tr>)}{!intentEntries.length ? emptyRow : null}</tbody></table></WorkspaceTableScroll></TabsContent>
      </>}
    </Tabs>
    <Dialog open={editor !== null} onOpenChange={open => { if (!open) setEditor(null) }}><DialogContent className={ws.dialog}><DialogHeader className={ws.dialogHeader}><DialogTitle>{editor?.kind === 'glossary' ? '编辑术语' : editor?.kind === 'patterns' ? '编辑问题模式' : '编辑意图'}</DialogTitle><DialogDescription>完成编辑后，在管理表中保存当前类别的规则。</DialogDescription></DialogHeader><div className={cn(ws.dialogBody, 'space-y-5')}>
      {editor?.kind === 'glossary' ? <><label className="block space-y-2 text-sm"><span>术语</span><Input value={editor.value.term} onChange={event => setEditor({ ...editor, value: { ...editor.value, term: event.target.value } })} /></label><label className="block space-y-2 text-sm"><span>别名，逗号分隔</span><Input value={editor.value.aliasesText} onChange={event => setEditor({ ...editor, value: { ...editor.value, aliasesText: event.target.value } })} /></label></> : editor?.kind === 'patterns' ? <><label className="block space-y-2 text-sm"><span>触发词，逗号分隔</span><Input value={editor.value.markersText} onChange={event => setEditor({ ...editor, value: { ...editor.value, markersText: event.target.value } })} /></label><label className="block space-y-2 text-sm"><span>澄清话术</span><Input value={editor.value.followup} onChange={event => setEditor({ ...editor, value: { ...editor.value, followup: event.target.value } })} /></label><label className={ws.formRow}><span>启用此模式</span><Checkbox checked={editor.value.enabled} onCheckedChange={value => setEditor({ ...editor, value: { ...editor.value, enabled: value === true } })} /></label></> : editor?.kind === 'intents' ? <>{[['name', '意图名称'], ['keywordsText', '关键词，逗号分隔'], ['route', '检索路由']].map(([field, label]) => <label className="block space-y-2 text-sm" key={field}><span>{label}</span><Input value={editor.value[field as 'name' | 'keywordsText' | 'route']} onChange={event => setEditor({ ...editor, value: { ...editor.value, [field]: event.target.value } })} /></label>)}</> : null}
    </div><DialogFooter className={ws.dialogFooter}><Button variant="outline" onClick={() => setEditor(null)}>取消</Button><Button onClick={commitEditor}>完成编辑</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={tool !== null} onOpenChange={open => { if (!open) setTool(null) }}><DialogContent className={cn(ws.dialog, tool === 'suggestions' && ws.wideDialog)}><DialogHeader className={ws.dialogHeader}><DialogTitle>{tool === 'preview' ? '查询改写预览' : '规则候选'}</DialogTitle><DialogDescription>{tool === 'preview' ? '使用已保存规则，未保存的编辑不会参与预览。' : '接受的候选进入本地术语表，再通过“保存术语”写入规则库。'}</DialogDescription></DialogHeader><div className={ws.dialogBody}>
      {tool === 'preview' ? <><Label htmlFor="industry-rules-preview-query">输入问题</Label><Input id="industry-rules-preview-query" className="mt-2" value={previewQuery} onChange={event => setPreviewQuery(event.target.value)} placeholder="输入要测试的问题" />{previewError ? <WorkspaceNotice>{previewError}</WorkspaceNotice> : previewing ? <p role="status" className={ws.empty}>正在计算改写预览…</p> : preview ? <section className={ws.section}><dl className="space-y-5 text-sm leading-6"><div><dt className="text-muted-foreground">原问题</dt><dd>{preview.originalQuery}</dd></div><div><dt className="text-muted-foreground">改写后</dt><dd>{preview.expandedQuery}</dd></div></dl><Badge className="mt-5" variant="outline">{preview.changed ? '已命中规则并改写' : '未触发改写'}</Badge></section> : <p className={ws.empty}>输入问题后查看改写结果</p>}</> : <><Label htmlFor="industry-rules-dataset">候选来源数据集</Label><Select value={selectedDatasetId} onValueChange={value => { setSelectedDatasetId(value); setGlossarySuggestions([]); setSelectedSuggestionTokens({}) }} disabled={loadingMeta}><SelectTrigger id="industry-rules-dataset" className="mt-2"><SelectValue placeholder="选择数据集" /></SelectTrigger><SelectContent>{datasets.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent></Select><div className="my-4 flex items-center justify-between gap-3"><span className={ws.muted}>已选 {selectedSuggestionCount} 条</span><Button variant="outline" disabled={!selectedSuggestionCount} onClick={acceptSelectedSuggestions}>批量接受</Button></div>{glossarySuggestionsQuery.isError ? <WorkspaceNotice retry={() => { void glossarySuggestionsQuery.refetch() }}>{formatApiError(glossarySuggestionsQuery.error, '候选读取失败')}</WorkspaceNotice> : loadingSuggestions ? <p className={ws.empty}>正在读取候选…</p> : <div className={ws.tableScroll}><table className={ws.table}><thead><tr><th>选择</th><th>术语</th><th>命中次数</th><th>来源</th><th>操作</th></tr></thead><tbody>{visibleGlossarySuggestions.map(entry => <tr key={entry.token}><td><Checkbox aria-label={`选择候选 ${entry.token}`} checked={selectedSuggestionTokens[entry.token] === true} onCheckedChange={value => setSelectedSuggestionTokens(prev => ({ ...prev, [entry.token]: value === true }))} /></td><td>{entry.token}</td><td>{entry.count}</td><td>{entry.source}</td><td><div className="flex gap-2"><Button variant="ghost" onClick={() => addGlossarySuggestion(entry.token)}>接受</Button><Button variant="ghost" onClick={() => setDismissedSuggestionTokens(prev => ({ ...prev, [entry.token]: true }))}>拒绝</Button></div></td></tr>)}</tbody></table>{!visibleGlossarySuggestions.length ? <p className={ws.empty}>当前范围暂无待审核候选</p> : null}</div>}</>}
    </div><DialogFooter className={ws.dialogFooter}><Button variant="outline" onClick={() => setTool(null)}>关闭</Button></DialogFooter></DialogContent></Dialog>
  </OperationalWorkspace>
}
