'use client'

import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink, Loader2, Plus, RefreshCw, Save, Trash2 } from '@/components/icons'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  OperationalWorkspace,
  WorkspaceTableScroll,
  WorkspaceNotice,
  WorkspaceNoticeStack,
  workspaceStyles as ws,
} from '@/components/ui/operational-workspace'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatApiError } from '@/lib/api-errors'
import { datasetApi } from '@/lib/api/datasets'
import { industryRulesApi } from '@/lib/api/industry-rules'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { downloadBlob } from '@/lib/download'
import { queryKeys } from '@/lib/query-keys'
import { randomBase36Id } from '@/lib/secure-random'
import { cn } from '@/lib/utils'
import type { IndustryRulesRewritePreviewResponse } from '@/types/backend'
import {
  createRuleRow,
  isRuleSection,
  rowsFromValue,
  serializeRows,
  type RuleRow,
  type RuleSection,
} from './rule-editor-model'

type RuleRows = Record<RuleSection, readonly RuleRow[]>

const RULE_LABELS = {
  glossary: { name: '术语', add: '新增术语', save: '保存术语', saved: '术语已保存' },
  patterns: { name: '问题模式', add: '新增模式', save: '保存模式', saved: '问题模式已保存' },
  intents: { name: '意图分类', add: '新增意图', save: '保存意图', saved: '意图分类已保存' },
}

export function IndustryRulesWorkbench() {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return <IndustryRulesWorkspace key={sessionKey} sessionKey={sessionKey} />
}

function IndustryRulesWorkspace({ sessionKey }: Readonly<{ sessionKey: string }>) {
  const [selectedRuleset, setSelectedRuleset] = useState('')
  const [selectedDatasetId, setSelectedDatasetId] = useState('')
  const [searchValue, setSearchValue] = useState('')
  const [previewQuery, setPreviewQuery] = useState('')
  const [tool, setTool] = useState<'preview' | 'suggestions' | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [operationError, setOperationError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<RuleSection>('glossary')
  const [editor, setEditor] = useState<{ kind: RuleSection; value: RuleRow; rows: readonly RuleRow[] } | null>(null)

  const [previewing, setPreviewing] = useState(false)
  const [busy, setBusy] = useState(false)
  const saveRef = useRef<symbol | null>(null)
  const [drafts, setDrafts] = useState(() => new Map<string, Partial<RuleRows>>())
  const [selectedSuggestionTokens, setSelectedSuggestionTokens] = useState<Record<string, boolean>>({})
  const [dismissedSuggestionTokens, setDismissedSuggestionTokens] = useState<Record<string, boolean>>({})
  const [preview, setPreview] = useState<IndustryRulesRewritePreviewResponse | null>(null)

  const rulesetsQuery = useQuery({
    queryKey: queryKeys.industryRules.rulesets,
    queryFn: industryRulesApi.listRulesets,
  })
  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive(),
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
  })
  const rulesetDetailQuery = useQuery({
    queryKey: queryKeys.industryRules.ruleset(selectedRuleset),
    enabled: Boolean(selectedRuleset.trim()),
    queryFn: ({ signal }) => industryRulesApi.getRuleset(selectedRuleset, { signal }),
  })
  const glossarySuggestionsQuery = useQuery({
    queryKey: queryKeys.industryRules.glossarySuggestions(selectedDatasetId, selectedRuleset, { limit: 20 }),
    enabled: tool === 'suggestions' && selectedDatasetId !== '' && selectedRuleset !== '',
    queryFn: ({ signal }) =>
      datasetApi.getAnalysisRuleSuggestions(selectedDatasetId, { ruleset: selectedRuleset, limit: 20 }, { signal }),
  })

  const rulesets = useMemo(() => rulesetsQuery.data?.rulesets || [], [rulesetsQuery.data?.rulesets])
  const datasets = useMemo(() => datasetsQuery.data || [], [datasetsQuery.data])
  const loadingMeta = rulesetsQuery.isFetching || datasetsQuery.isFetching
  const metaError = rulesetsQuery.error || datasetsQuery.error
  const loadingRuleset = selectedRuleset !== '' && rulesetDetailQuery.isPending
  const loadingSuggestions = glossarySuggestionsQuery.isFetching
  const glossarySuggestions = glossarySuggestionsQuery.data?.glossary_suggestions

  const savedRows = useMemo<RuleRows | undefined>(() => {
    const ruleset = rulesetDetailQuery.data?.ruleset
    if (ruleset === undefined) return undefined
    return {
      glossary: rowsFromValue('glossary', ruleset.glossary).sort((a, b) => a.term.localeCompare(b.term, 'zh-CN')),
      patterns: rowsFromValue('patterns', ruleset.patterns),
      intents: rowsFromValue('intents', ruleset.intents),
    }
  }, [rulesetDetailQuery.data])
  const draft = drafts.get(selectedRuleset)
  const currentRows = savedRows === undefined ? undefined : { ...savedRows, ...draft }

  useLayoutEffect(() => {
    return () => {
      saveRef.current = null
    }
  }, [])

  const refreshMeta = () => {
    rulesetsQuery.refetch()
    datasetsQuery.refetch()
  }

  useEffect(() => {
    if (!selectedRuleset && rulesets[0]?.name) setSelectedRuleset(rulesets[0].name)
  }, [rulesets, selectedRuleset])

  useEffect(() => {
    if (!selectedDatasetId && datasets[0]?.id) setSelectedDatasetId(datasets[0].id)
  }, [datasets, selectedDatasetId])

  useEffect(() => {
    setPreview(null)
    setPreviewError(null)
    setPreviewing(false)
    const query = previewQuery.trim()
    if (tool !== 'preview' || selectedRuleset === '' || query === '') return

    const controller = new AbortController()
    const { signal } = controller
    async function loadPreview() {
      setPreviewing(true)
      try {
        const response = await industryRulesApi.previewRewrite({ ruleset: selectedRuleset, query }, { signal })
        if (!signal.aborted) setPreview(response)
      } catch (error) {
        if (!signal.aborted) setPreviewError(formatApiError(error, '改写预览失败'))
      } finally {
        if (!signal.aborted) setPreviewing(false)
      }
    }

    const timer = window.setTimeout(() => void loadPreview(), 280)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [previewQuery, selectedRuleset, tool])

  const keyword = searchValue.trim().toLowerCase()
  const visibleRows =
    currentRows === undefined
      ? undefined
      : {
          glossary: currentRows.glossary.filter((row) => `${row.term} ${row.words}`.toLowerCase().includes(keyword)),
          patterns: currentRows.patterns.filter((row) =>
            `${row.words} ${row.followup}`.toLowerCase().includes(keyword),
          ),
          intents: currentRows.intents.filter((row) =>
            `${row.name} ${row.words} ${row.route}`.toLowerCase().includes(keyword),
          ),
        }
  const glossaryEntries = currentRows?.glossary
  const visibleGlossarySuggestions = useMemo(() => {
    if (glossarySuggestions === undefined) return []
    const existingTerms = new Set(glossaryEntries?.map((row) => row.term.trim()))
    return glossarySuggestions.filter(
      (entry) => dismissedSuggestionTokens[entry.token] !== true && !existingTerms.has(entry.token),
    )
  }, [dismissedSuggestionTokens, glossaryEntries, glossarySuggestions])
  const selectedSuggestions = visibleGlossarySuggestions.filter(
    (entry) => selectedSuggestionTokens[entry.token] === true,
  )

  function updateRows(
    section: RuleSection,
    rows: readonly RuleRow[],
    update: (rows: readonly RuleRow[]) => readonly RuleRow[],
  ) {
    if (saveRef.current !== null) return
    setDrafts((previous) => {
      const rulesetDraft = previous.get(selectedRuleset)
      const previousRows = rulesetDraft?.[section] ?? rows
      const nextRows = update(previousRows)
      if (nextRows === previousRows) return previous
      const next = new Map(previous)
      next.set(selectedRuleset, { ...rulesetDraft, [section]: nextRows })
      return next
    })
    setOperationError(null)
  }

  function removeRow(section: RuleSection, id: string) {
    if (currentRows === undefined) return
    updateRows(section, currentRows[section], (rows) => rows.filter((row) => row.id !== id))
  }

  const addGlossarySuggestion = (token: string) => {
    if (glossaryEntries === undefined || saveRef.current !== null) return
    const term = token.trim()
    if (term === '') return
    const row = { ...createRuleRow(randomBase36Id(10)), term }
    updateRows('glossary', glossaryEntries, (rows) =>
      rows.some((entry) => entry.term.trim() === term) ? rows : [...rows, row],
    )
    setDismissedSuggestionTokens((prev) => ({ ...prev, [term]: true }))
  }

  const acceptSelectedSuggestions = () => {
    for (const suggestion of selectedSuggestions) {
      addGlossarySuggestion(suggestion.token)
    }
    setSelectedSuggestionTokens({})
  }

  async function saveCurrent() {
    if (currentRows === undefined || saveRef.current !== null || getAuthSessionKey() !== sessionKey) return
    const ruleset = selectedRuleset
    const section = activeTab
    const operation = Symbol()
    const isCurrent = () => saveRef.current === operation && getAuthSessionKey() === sessionKey
    saveRef.current = operation
    setBusy(true)
    setOperationError(null)
    try {
      if (section === 'glossary') {
        await industryRulesApi.updateGlossary(ruleset, { glossary: serializeRows(section, currentRows.glossary) })
      } else if (section === 'patterns') {
        await industryRulesApi.updatePatterns(ruleset, { patterns: serializeRows(section, currentRows.patterns) })
      } else {
        await industryRulesApi.updateIntents(ruleset, { intents: serializeRows(section, currentRows.intents) })
      }
      if (!isCurrent()) return

      try {
        await rulesetDetailQuery.refetch({ throwOnError: true })
      } catch {
        if (isCurrent()) setOperationError('修改已提交，但暂时无法读回结果。草稿已保留。')
        return
      }
      if (!isCurrent()) return
      setDrafts((previous) => {
        const rulesetDraft = previous.get(ruleset)
        if (rulesetDraft === undefined) return previous
        const remaining = { ...rulesetDraft }
        delete remaining[section]
        const next = new Map(previous)
        if (Object.keys(remaining).length === 0) next.delete(ruleset)
        else next.set(ruleset, remaining)
        return next
      })
      toast.success(RULE_LABELS[section].saved)
    } catch (error) {
      if (isCurrent()) setOperationError(formatApiError(error, `保存${RULE_LABELS[section].name}失败`))
    } finally {
      if (saveRef.current === operation) {
        saveRef.current = null
        if (getAuthSessionKey() === sessionKey) setBusy(false)
      }
    }
  }

  function exportCurrentRuleset() {
    if (currentRows === undefined) return
    setOperationError(null)
    try {
      const payload = {
        ruleset: selectedRuleset,
        glossary: serializeRows('glossary', currentRows.glossary),
        patterns: serializeRows('patterns', currentRows.patterns),
        intents: serializeRows('intents', currentRows.intents),
      }
      downloadBlob(
        `${selectedRuleset}.json`,
        new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' }),
      )
    } catch (error) {
      setOperationError(formatApiError(error, '导出行业规则失败'))
    }
  }

  function openEditor(section: RuleSection, row?: RuleRow) {
    if (currentRows === undefined || saveRef.current !== null) return
    setEditor({ kind: section, rows: currentRows[section], value: row ?? createRuleRow(randomBase36Id(10)) })
  }

  function commitEditor() {
    if (editor === null || saveRef.current !== null) return
    const { kind, value, rows } = editor
    updateRows(kind, rows, (previous) =>
      previous.some((row) => row.id === value.id)
        ? previous.map((row) => (row.id === value.id ? value : row))
        : [...previous, value],
    )
    setEditor(null)
  }
  const emptyRow = (
    <tr>
      <td colSpan={4}>
        <div className={ws.empty}>{keyword ? '没有匹配的规则' : '当前规则集暂无此类规则'}</div>
      </td>
    </tr>
  )
  return (
    <OperationalWorkspace
      title="行业规则"
      icon="governance-config"
      context={selectedRuleset || '未选择规则集'}
      actions={
        <>
          <Button variant="outline" disabled={!selectedRuleset} onClick={() => setTool('preview')}>
            查询预览
          </Button>
          <Button variant="outline" disabled={busy} onClick={() => setTool('suggestions')}>
            规则候选
          </Button>
          <Button
            variant="ghost"
            aria-label="导出当前规则集"
            disabled={currentRows === undefined || busy}
            onClick={exportCurrentRuleset}
          >
            <ExternalLink />
          </Button>
        </>
      }
      toolbar={
        <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto">
          <Label htmlFor="industry-rules-ruleset" className="shrink-0">
            规则集
          </Label>
          <Select
            value={selectedRuleset}
            disabled={loadingMeta || busy || editor !== null}
            onValueChange={(value) => {
              if (saveRef.current !== null) return
              setSelectedRuleset(value)
              setSelectedSuggestionTokens({})
              setDismissedSuggestionTokens({})
              setOperationError(null)
            }}
          >
            <SelectTrigger id="industry-rules-ruleset" className="min-w-0 flex-1 sm:w-64 sm:flex-none">
              <SelectValue placeholder="选择规则集" />
            </SelectTrigger>
            <SelectContent>
              {rulesets.map((item) => (
                <SelectItem key={item.name} value={item.name}>
                  {item.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="ghost"
            size="icon"
            className="shrink-0"
            aria-label="重新读取规则目录"
            disabled={loadingMeta || busy}
            onClick={refreshMeta}
          >
            <RefreshCw />
          </Button>
        </div>
      }
    >
      {metaError || rulesetDetailQuery.isError || operationError ? (
        <WorkspaceNoticeStack ariaLabel="行业规则状态提示">
          {metaError ? (
            <WorkspaceNotice
              tone="warning"
              title="加载规则集或数据集失败"
              error={metaError}
              fallbackMessage="加载规则集或数据集失败"
              retry={refreshMeta}
            />
          ) : null}
          {rulesetDetailQuery.isError ? (
            <WorkspaceNotice
              tone="warning"
              title="加载规则详情失败"
              error={rulesetDetailQuery.error}
              fallbackMessage="加载规则详情失败"
              pending={busy || rulesetDetailQuery.isFetching}
              retry={() => {
                void rulesetDetailQuery.refetch()
              }}
            />
          ) : null}
          {operationError ? <WorkspaceNotice>{operationError}</WorkspaceNotice> : null}
        </WorkspaceNoticeStack>
      ) : null}
      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          if (isRuleSection(value)) setActiveTab(value)
        }}
      >
        <TabsList className={ws.tabList}>
          <TabsTrigger value="glossary">术语 {currentRows?.glossary.length}</TabsTrigger>
          <TabsTrigger value="patterns">问题模式 {currentRows?.patterns.length}</TabsTrigger>
          <TabsTrigger value="intents">意图分类 {currentRows?.intents.length}</TabsTrigger>
        </TabsList>
        <div className="my-3 flex items-center justify-between gap-2 sm:my-5 sm:flex-wrap sm:gap-3">
          <Input
            className="min-w-0 flex-1 sm:w-72 sm:flex-none"
            aria-label="搜索行业规则"
            placeholder="搜索规则内容"
            value={searchValue}
            onChange={(event) => setSearchValue(event.currentTarget.value)}
          />
          <div className="flex shrink-0 gap-2">
            <Button
              className="max-sm:size-11 max-sm:p-0"
              title={RULE_LABELS[activeTab].add}
              variant="outline"
              onClick={() => openEditor(activeTab)}
              disabled={currentRows === undefined || busy}
            >
              <Plus />
              <span className="max-sm:sr-only">{RULE_LABELS[activeTab].add}</span>
            </Button>
            <Button
              className="max-sm:size-11 max-sm:p-0"
              title={RULE_LABELS[activeTab].save}
              disabled={currentRows === undefined || busy}
              onClick={() => void saveCurrent()}
            >
              {busy ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Save />}
              <span className="max-sm:sr-only">{RULE_LABELS[activeTab].save}</span>
            </Button>
          </div>
        </div>
        {loadingRuleset ? (
          <p role="status" className={ws.empty}>
            正在读取规则…
          </p>
        ) : visibleRows !== undefined ? (
          <>
            <TabsContent value="glossary" className={ws.tabContent}>
              <WorkspaceTableScroll label="术语管理表格" stickyActions>
                <table className={cn(ws.table, 'min-w-[580px]')}>
                  <thead>
                    <tr>
                      <th>术语</th>
                      <th>别名</th>
                      <th>来源</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.glossary.map((entry) => (
                      <tr key={entry.id}>
                        <td className="font-medium">{entry.term || '未填写术语'}</td>
                        <td>{entry.words || '—'}</td>
                        <td>规则库</td>
                        <td>
                          <div className="flex gap-2">
                            <Button variant="ghost" disabled={busy} onClick={() => openEditor('glossary', entry)}>
                              编辑
                            </Button>
                            <Button
                              variant="ghost"
                              aria-label={`删除术语 ${entry.term}`}
                              disabled={busy}
                              onClick={() => removeRow('glossary', entry.id)}
                            >
                              <Trash2 />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                    {visibleRows.glossary.length === 0 ? emptyRow : null}
                  </tbody>
                </table>
              </WorkspaceTableScroll>
            </TabsContent>
            <TabsContent value="patterns" className={ws.tabContent}>
              <WorkspaceTableScroll label="问题模式表格" stickyActions>
                <table className={cn(ws.table, 'min-w-[660px]')}>
                  <thead>
                    <tr>
                      <th>触发词</th>
                      <th>澄清话术</th>
                      <th>状态</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.patterns.map((entry) => (
                      <tr key={entry.id}>
                        <td className="font-medium">{entry.words || '未填写触发词'}</td>
                        <td>{entry.followup || '—'}</td>
                        <td>
                          <Badge variant={entry.enabled ? 'soft' : 'outline'}>{entry.enabled ? '启用' : '停用'}</Badge>
                        </td>
                        <td>
                          <div className="flex gap-2">
                            <Button variant="ghost" disabled={busy} onClick={() => openEditor('patterns', entry)}>
                              编辑
                            </Button>
                            <Button
                              variant="ghost"
                              aria-label="删除问题模式"
                              disabled={busy}
                              onClick={() => removeRow('patterns', entry.id)}
                            >
                              <Trash2 />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                    {visibleRows.patterns.length === 0 ? emptyRow : null}
                  </tbody>
                </table>
              </WorkspaceTableScroll>
            </TabsContent>
            <TabsContent value="intents" className={ws.tabContent}>
              <WorkspaceTableScroll label="意图分类表格" stickyActions>
                <table className={cn(ws.table, 'min-w-[660px]')}>
                  <thead>
                    <tr>
                      <th>意图名称</th>
                      <th>关键词</th>
                      <th>检索路由</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.intents.map((entry) => (
                      <tr key={entry.id}>
                        <td className="font-medium">{entry.name || '未填写意图'}</td>
                        <td>{entry.words || '—'}</td>
                        <td>{entry.route}</td>
                        <td>
                          <div className="flex gap-2">
                            <Button variant="ghost" disabled={busy} onClick={() => openEditor('intents', entry)}>
                              编辑
                            </Button>
                            <Button
                              variant="ghost"
                              aria-label={`删除意图 ${entry.name}`}
                              disabled={busy}
                              onClick={() => removeRow('intents', entry.id)}
                            >
                              <Trash2 />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                    {visibleRows.intents.length === 0 ? emptyRow : null}
                  </tbody>
                </table>
              </WorkspaceTableScroll>
            </TabsContent>
          </>
        ) : null}
      </Tabs>
      <Dialog
        open={editor !== null}
        onOpenChange={(open) => {
          if (!open) setEditor(null)
        }}
      >
        <DialogContent className={ws.dialog}>
          <DialogHeader className={ws.dialogHeader}>
            <DialogTitle>
              {editor?.kind === 'glossary' ? '编辑术语' : editor?.kind === 'patterns' ? '编辑问题模式' : '编辑意图'}
            </DialogTitle>
            <DialogDescription>完成编辑后，在管理表中保存当前类别的规则。</DialogDescription>
          </DialogHeader>
          <div className={cn(ws.dialogBody, 'space-y-5')}>
            {editor?.kind === 'glossary' ? (
              <>
                <label className="block space-y-2 text-sm">
                  <span>术语</span>
                  <Input
                    value={editor.value.term}
                    onChange={(event) => setEditor({ ...editor, value: { ...editor.value, term: event.target.value } })}
                  />
                </label>
                <label className="block space-y-2 text-sm">
                  <span>别名，逗号分隔</span>
                  <Input
                    value={editor.value.words}
                    onChange={(event) =>
                      setEditor({ ...editor, value: { ...editor.value, words: event.currentTarget.value } })
                    }
                  />
                </label>
              </>
            ) : editor?.kind === 'patterns' ? (
              <>
                <label className="block space-y-2 text-sm">
                  <span>触发词，逗号分隔</span>
                  <Input
                    value={editor.value.words}
                    onChange={(event) =>
                      setEditor({ ...editor, value: { ...editor.value, words: event.currentTarget.value } })
                    }
                  />
                </label>
                <label className="block space-y-2 text-sm">
                  <span>澄清话术</span>
                  <Input
                    value={editor.value.followup}
                    onChange={(event) =>
                      setEditor({ ...editor, value: { ...editor.value, followup: event.target.value } })
                    }
                  />
                </label>
                <label className={ws.formRow}>
                  <span>启用此模式</span>
                  <Checkbox
                    checked={editor.value.enabled}
                    onCheckedChange={(value) =>
                      setEditor({ ...editor, value: { ...editor.value, enabled: value === true } })
                    }
                  />
                </label>
              </>
            ) : editor?.kind === 'intents' ? (
              <>
                {(
                  [
                    ['name', '意图名称'],
                    ['words', '关键词，逗号分隔'],
                    ['route', '检索路由'],
                  ] as const
                ).map(([field, label]) => (
                  <label className="block space-y-2 text-sm" key={field}>
                    <span>{label}</span>
                    <Input
                      value={editor.value[field]}
                      onChange={(event) =>
                        setEditor({ ...editor, value: { ...editor.value, [field]: event.currentTarget.value } })
                      }
                    />
                  </label>
                ))}
              </>
            ) : null}
          </div>
          <DialogFooter className={ws.dialogFooter}>
            <Button variant="outline" onClick={() => setEditor(null)}>
              取消
            </Button>
            <Button onClick={commitEditor}>完成编辑</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={tool !== null}
        onOpenChange={(open) => {
          if (!open) setTool(null)
        }}
      >
        <DialogContent className={cn(ws.dialog, tool === 'suggestions' && ws.wideDialog)}>
          <DialogHeader className={ws.dialogHeader}>
            <DialogTitle>{tool === 'preview' ? '查询改写预览' : '规则候选'}</DialogTitle>
            <DialogDescription>
              {tool === 'preview'
                ? '使用已保存规则，未保存的编辑不会参与预览。'
                : '接受的候选进入本地术语表，再通过“保存术语”写入规则库。'}
            </DialogDescription>
          </DialogHeader>
          <div className={ws.dialogBody}>
            {tool === 'preview' ? (
              <>
                <Label htmlFor="industry-rules-preview-query">输入问题</Label>
                <Input
                  id="industry-rules-preview-query"
                  className="mt-2"
                  value={previewQuery}
                  onChange={(event) => setPreviewQuery(event.target.value)}
                  placeholder="输入要测试的问题"
                />
                {previewError ? (
                  <WorkspaceNotice>{previewError}</WorkspaceNotice>
                ) : previewing ? (
                  <p role="status" className={ws.empty}>
                    正在计算改写预览…
                  </p>
                ) : preview?.ruleset === selectedRuleset && preview.original_query === previewQuery.trim() ? (
                  <section className={ws.section}>
                    <dl className="space-y-5 text-sm leading-6">
                      <div>
                        <dt className="text-muted-foreground">原问题</dt>
                        <dd>{preview.original_query}</dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground">改写后</dt>
                        <dd>{preview.expanded_query}</dd>
                      </div>
                    </dl>
                    <Badge className="mt-5" variant="outline">
                      {preview.changed ? '已命中规则并改写' : '未触发改写'}
                    </Badge>
                  </section>
                ) : (
                  <p className={ws.empty}>输入问题后查看改写结果</p>
                )}
              </>
            ) : (
              <>
                <Label htmlFor="industry-rules-dataset">候选来源数据集</Label>
                <Select
                  value={selectedDatasetId}
                  onValueChange={(value) => {
                    setSelectedDatasetId(value)
                    setSelectedSuggestionTokens({})
                    setDismissedSuggestionTokens({})
                  }}
                  disabled={loadingMeta}
                >
                  <SelectTrigger id="industry-rules-dataset" className="mt-2">
                    <SelectValue placeholder="选择数据集" />
                  </SelectTrigger>
                  <SelectContent>
                    {datasets.map((item) => (
                      <SelectItem key={item.id} value={item.id}>
                        {item.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="my-4 flex items-center justify-between gap-3">
                  <span className={ws.muted}>已选 {selectedSuggestions.length} 条</span>
                  <Button
                    variant="outline"
                    disabled={
                      busy ||
                      loadingSuggestions ||
                      glossarySuggestionsQuery.isError ||
                      glossaryEntries === undefined ||
                      selectedSuggestions.length === 0
                    }
                    onClick={acceptSelectedSuggestions}
                  >
                    批量接受
                  </Button>
                </div>
                {glossarySuggestionsQuery.isError ? (
                  <WorkspaceNotice
                    retry={() => {
                      void glossarySuggestionsQuery.refetch()
                    }}
                  >
                    {formatApiError(glossarySuggestionsQuery.error, '候选读取失败')}
                  </WorkspaceNotice>
                ) : loadingSuggestions ? (
                  <p className={ws.empty}>正在读取候选…</p>
                ) : (
                  <div className={ws.tableScroll}>
                    <table className={ws.table}>
                      <thead>
                        <tr>
                          <th>选择</th>
                          <th>术语</th>
                          <th>命中次数</th>
                          <th>来源</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {visibleGlossarySuggestions.map((entry) => (
                          <tr key={entry.token}>
                            <td>
                              <Checkbox
                                aria-label={`选择候选 ${entry.token}`}
                                checked={selectedSuggestionTokens[entry.token] === true}
                                onCheckedChange={(value) =>
                                  setSelectedSuggestionTokens((prev) => ({ ...prev, [entry.token]: value === true }))
                                }
                              />
                            </td>
                            <td>{entry.token}</td>
                            <td>{entry.count}</td>
                            <td>{entry.source}</td>
                            <td>
                              <div className="flex gap-2">
                                <Button
                                  variant="ghost"
                                  disabled={glossaryEntries === undefined}
                                  onClick={() => addGlossarySuggestion(entry.token)}
                                >
                                  接受
                                </Button>
                                <Button
                                  variant="ghost"
                                  onClick={() =>
                                    setDismissedSuggestionTokens((prev) => ({ ...prev, [entry.token]: true }))
                                  }
                                >
                                  拒绝
                                </Button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!visibleGlossarySuggestions.length ? <p className={ws.empty}>当前范围暂无待审核候选</p> : null}
                  </div>
                )}
              </>
            )}
          </div>
          <DialogFooter className={ws.dialogFooter}>
            <Button variant="outline" onClick={() => setTool(null)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </OperationalWorkspace>
  )
}
