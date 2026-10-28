'use client'
import { FeedbackToast } from '@/components/feedback-toast'

import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowRight, ExternalLink, Loader2, Plus, Search } from '@/components/icons'

import { Link } from '@/i18n/navigation'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { settingsLayoutTokens } from '@/components/ui/system-page-tokens'
import { RuleRowsEditor } from './industry-rule-rows-editor'
import {
  createRuleDraft, createRuleRow, createRulesetDraft, draftValue, isRuleDraftDirty,
  rowsFromValue, type RuleDraft, type RuleRow, type RuleSection, type RulesetDraft,
} from '@/components/industry-rules/rule-editor-model'
import { industryRulesApi, type IndustryRulesRewritePreviewResponse } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { randomBase36Id } from '@/lib/secure-random'
import { cn, detachPromise } from '@/lib/utils'
import styles from '../settings.module.css'

const sections: RuleSection[] = ['glossary', 'patterns', 'intents']
const meta = {
  glossary: { title: '术语词库', add: '新增术语', save: '保存词库', hint: '问题中出现术语时，补充对应的检索扩展词。多个词用逗号分隔。' },
  patterns: { title: '匹配规则', add: '新增规则', save: '保存规则', hint: '维护触发词与澄清话术。多个触发词用逗号分隔。' },
  intents: { title: '意图规则', add: '新增意图', save: '保存意图', hint: '用关键词区分问题意图，并配置对应路由。多个关键词用逗号分隔。' },
}
const inputClass = cn(settingsLayoutTokens.input, 'border-transparent bg-[var(--settings-value)] placeholder:text-muted-foreground focus-visible:border-input')
const actionClass = 'h-11 shrink-0 gap-1.5 px-3 text-[13px] font-medium sm:h-10'
const secondaryActionClass = cn(actionClass, 'hover:bg-[var(--settings-active)] hover:text-foreground')
type RemovedRow = { ruleset: string; section: RuleSection; row: RuleRow; index: number }

function rowCount(section: RuleSection, draft: RuleDraft): number | string {
  if (draft.json === null) return draft.rows.length
  try { return Object.keys(draftValue(section, draft)).length } catch { return '—' }
}

export function IndustryRulesSection() {
  const queryClient = useQueryClient()
  const [selection, setSelection] = useState('')
  const [activeSection, setActiveSection] = useState<RuleSection>('glossary')
  const [drafts, setDrafts] = useState<Record<string, RulesetDraft>>({})
  const [filter, setFilter] = useState('')
  const [focusRowId, setFocusRowId] = useState<string | null>(null)
  const [removed, setRemoved] = useState<RemovedRow | null>(null)
  const [saving, setSaving] = useState(false)
  const [editorError, setEditorError] = useState<string | null>(null)
  const [testQuery, setTestQuery] = useState('485 通信异常怎么排查？')
  const [testing, setTesting] = useState(false)
  const [preview, setPreview] = useState<IndustryRulesRewritePreviewResponse | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)

  const rulesetsQuery = useQuery({ queryKey: queryKeys.industryRules.rulesets, queryFn: () => industryRulesApi.listRulesets() })
  const rulesets = rulesetsQuery.data?.rulesets ?? []
  const rulesetName = rulesets.some(item => item.name === selection) ? selection : rulesets.find(item => item.name === 'industrial_control')?.name ?? rulesets[0]?.name ?? ''
  const detailQuery = useQuery({
    queryKey: queryKeys.industryRules.ruleset(rulesetName),
    queryFn: () => industryRulesApi.getRuleset(rulesetName),
    enabled: Boolean(rulesetName),
    retry: 1,
  })
  const current = Object.hasOwn(drafts, rulesetName) ? drafts[rulesetName] : undefined
  const activeDraft = current?.[activeSection]
  const dirty = activeDraft ? isRuleDraftDirty(activeSection, activeDraft) : false
  const glossaryDirty = current ? isRuleDraftDirty('glossary', current.glossary) : false
  const currentPreview = preview?.ruleset === rulesetName ? preview : null

  useEffect(() => {
    const detail = detailQuery.data?.ruleset
    if (!detail || detail.name !== rulesetName) return
    setDrafts(previous => Object.hasOwn(previous, rulesetName) ? previous : { ...previous, [rulesetName]: createRulesetDraft(detail) })
  }, [detailQuery.data, rulesetName])

  function updateDraft(section: RuleSection, update: (draft: RuleDraft) => RuleDraft) {
    setDrafts(previous => {
      const ruleset = previous[rulesetName]
      return ruleset ? { ...previous, [rulesetName]: { ...ruleset, [section]: update(ruleset[section]) } } : previous
    })
    setEditorError(null)
  }

  function changeSection(section: RuleSection) {
    setActiveSection(section)
    setFilter('')
    setFocusRowId(null)
    setEditorError(null)
  }

  function changeMode() {
    if (!activeDraft) return
    try {
      const value = draftValue(activeSection, activeDraft)
      updateDraft(activeSection, draft => draft.json === null
        ? { ...draft, json: JSON.stringify(value, null, 2) }
        : { ...draft, rows: rowsFromValue(activeSection, value), json: null })
      setFilter('')
      setRemoved(null)
    } catch (error) { setEditorError(formatApiError(error, '无法切换编辑方式。')) }
  }

  async function save() {
    if (!activeDraft || !dirty || saving) return
    const name = rulesetName
    const section = activeSection
    // Keep invalid editor input associated with its field.
    try {
      draftValue(section, activeDraft)
    } catch (error) {
      setEditorError(formatApiError(error, '请检查规则内容。'))
      return
    }
    try {
      setSaving(true)
      setEditorError(null)
      if (section === 'glossary') await industryRulesApi.updateGlossary(name, { glossary: draftValue('glossary', activeDraft) })
      else if (section === 'patterns') await industryRulesApi.updatePatterns(name, { patterns: draftValue('patterns', activeDraft) })
      else await industryRulesApi.updateIntents(name, { intents: draftValue('intents', activeDraft) })
      // Read back the saved section, preserving drafts in the other two editors.
      let response
      try { response = await industryRulesApi.getRuleset(name) } catch {
        throw new Error('修改已提交，但暂时无法读回结果。草稿已保留，请重试保存。')
      }
      const savedValue = response.ruleset[section] ?? (section === 'glossary' ? {} : [])
      setDrafts(previous => ({ ...previous, [name]: { ...previous[name], [section]: { ...createRuleDraft(section, savedValue), json: activeDraft.json === null ? null : JSON.stringify(savedValue, null, 2) } } }))
      queryClient.setQueryData(queryKeys.industryRules.ruleset(name), response)
      detachPromise(queryClient.invalidateQueries({ queryKey: queryKeys.industryRules.rulesets }))
      setRemoved(null)
      if (section === 'glossary') setPreview(null)
    } catch (error) { toast.error(formatApiError(error, '保存失败，修改已保留，请重试。')) }
    finally { setSaving(false) }
  }

  async function testGlossary() {
    if (!current || !testQuery.trim() || glossaryDirty || testing || saving) return
    setTesting(true)
    setPreviewError(null)
    setPreview(null)
    try { setPreview(await industryRulesApi.previewRewrite({ ruleset: rulesetName, query: testQuery.trim() })) }
    catch (error) { setPreviewError(formatApiError(error, '测试失败，请重试。')) }
    finally { setTesting(false) }
  }

  const canUndo = removed?.ruleset === rulesetName && removed.section === activeSection

  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="w-full space-y-2 sm:w-80">
          <Label htmlFor="industry-ruleset" className="text-[14px] font-medium">规则集</Label>
          <Select value={rulesetName} onValueChange={name => { setSelection(name); setFilter(''); setEditorError(null); setPreviewError(null) }} disabled={saving || testing || !rulesets.length}>
            <SelectTrigger id="industry-ruleset" className={inputClass}><SelectValue placeholder="选择规则集" /></SelectTrigger>
            <SelectContent>{rulesets.map(item => <SelectItem key={item.name} value={item.name}>{item.name === 'industrial_control' ? '工业控制' : item.name}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <Link href="/governance/industry-rules" className="inline-flex min-h-11 items-center gap-1.5 rounded-sm text-[13px] text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:min-h-10">
          完整工作台<ExternalLink className="size-3.5" />
        </Link>
      </div>

      {!current ? (
        <div className="flex flex-wrap items-center gap-3 py-10 text-[14px] text-muted-foreground" role={rulesetsQuery.isError || detailQuery.isError ? 'alert' : 'status'}>
          {rulesetsQuery.isError || detailQuery.isError ? <><span>规则加载失败。</span><Button variant="outline" className={secondaryActionClass} onClick={() => { if (rulesetsQuery.isError) detachPromise(rulesetsQuery.refetch()); else detachPromise(detailQuery.refetch()) }}>重试加载</Button></>
            : rulesetsQuery.isPending || rulesetName ? <><Loader2 className="size-4 animate-spin motion-reduce:animate-none" />正在加载规则…</> : '暂无可用规则集。'}
        </div>
      ) : (
        <div className={styles.integrationLayout}>
          <div className="min-w-0">
            <Tabs value={activeSection} onValueChange={value => changeSection(value as RuleSection)}>
              <TabsList className={styles.ruleTabs} aria-label="规则类型">
                {sections.map(section => (
                  <TabsTrigger key={section} value={section} className={styles.ruleTab} disabled={saving}>
                    <span>{meta[section].title}</span><span data-rule-count className="text-[13px] font-normal tabular-nums text-muted-foreground">{rowCount(section, current[section])}</span>
                    {isRuleDraftDirty(section, current[section]) ? <span className="size-1 shrink-0 rounded-full bg-current"><span className="sr-only">（未保存）</span></span> : null}
                  </TabsTrigger>
                ))}
              </TabsList>
              {sections.map(section => {
                const draft = current[section]
                return (
                  <TabsContent key={section} value={section} className={styles.rulePanel}>
                    <p className="mb-4 text-[13px] leading-6 text-muted-foreground">{meta[section].hint}</p>
                    <fieldset disabled={saving} className="min-w-0">
                      {draft.json === null ? (
                        <>
                          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
                            <SearchInput aria-label={`搜索${meta[section].title}`} value={filter} onValueChange={setFilter} placeholder={section === 'glossary' ? '搜索术语或扩展词' : '搜索规则'} containerClassName="min-w-0 flex-1" inputClassName={inputClass} />
                            <Button id={`industry-add-${section}`} type="button" variant="outline" className={cn(secondaryActionClass, 'self-end sm:self-auto')} onClick={() => {
                              const row = createRuleRow(randomBase36Id(10))
                              updateDraft(section, previous => ({ ...previous, rows: [...previous.rows, row] }))
                              setFilter('')
                              setFocusRowId(row.id)
                            }}><Plus className="size-4" />{meta[section].add}</Button>
                          </div>
                          <RuleRowsEditor section={section} rows={draft.rows} filter={filter} focusRowId={focusRowId} onChange={(id, patch) => updateDraft(section, previous => ({ ...previous, rows: previous.rows.map(row => row.id === id ? { ...row, ...patch } : row) }))} onRemove={id => {
                            const index = draft.rows.findIndex(row => row.id === id)
                            const next = draft.rows[index + 1] ?? draft.rows[index - 1]
                            setFocusRowId(next?.id ?? null)
                            if (!next) document.getElementById(`industry-add-${section}`)?.focus()
                            setRemoved({ ruleset: rulesetName, section, row: draft.rows[index], index })
                            updateDraft(section, previous => ({ ...previous, rows: previous.rows.filter(row => row.id !== id) }))
                          }} />
                        </>
                      ) : (
                        <div>
                          <Label htmlFor={`industry-${section}-json`} className="mb-2 block text-[13px]">{meta[section].title} JSON</Label>
                          <Textarea id={`industry-${section}-json`} value={draft.json} onChange={event => updateDraft(section, previous => ({ ...previous, json: event.target.value }))} spellCheck={false} aria-invalid={Boolean(editorError)} aria-describedby={editorError ? 'industry-editor-error' : undefined} className="min-h-64 rounded-lg border-transparent bg-[var(--settings-value)] font-mono text-base leading-6 focus-visible:border-input sm:text-[13px]" />
                        </div>
                      )}
                    </fieldset>
                  </TabsContent>
                )
              })}
            </Tabs>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
              <Button type="button" variant="ghost" className="h-11 px-0 text-[13px] text-muted-foreground hover:bg-transparent hover:text-foreground sm:h-9" disabled={saving} onClick={changeMode}>{activeDraft?.json === null ? 'JSON 编辑' : '返回表单编辑'}</Button>
              {canUndo ? <Button type="button" variant="ghost" className="h-11 px-0 text-[13px] sm:h-9" disabled={saving} onClick={() => {
                if (!removed) return
                updateDraft(activeSection, previous => { const rows = [...previous.rows]; rows.splice(removed.index, 0, removed.row); return { ...previous, rows } })
                setRemoved(null)
              }}>撤销移除</Button> : null}
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
              <p role="status" className="text-[13px] text-muted-foreground">{saving ? '正在保存并核对结果…' : dirty ? '有未保存的修改' : '已保存'}</p>
              <Button type="button" className={actionClass} disabled={!dirty || saving} onClick={() => detachPromise(save())}>{saving ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : null}{saving ? '正在保存…' : meta[activeSection].save}</Button>
            </div>
            {editorError ? <p id="industry-editor-error" role="alert" className="mt-3 text-[13px] leading-6 text-destructive">{editorError}</p> : null}
          </div>

          <aside className={styles.integrationAside} aria-labelledby="industry-test-title">
            <h3 id="industry-test-title" className={styles.integrationTitle}>测试术语展开</h3>
            <p className="mt-2 text-[13px] leading-6 text-muted-foreground">使用已保存的术语词库。</p>
            <form className="mt-5 space-y-3" onSubmit={event => { event.preventDefault(); detachPromise(testGlossary()) }}>
              <Label htmlFor="industry-test-query" className="text-[13px] font-medium">测试问题</Label>
              <Textarea id="industry-test-query" value={testQuery} onChange={event => { setTestQuery(event.target.value); setPreview(null); setPreviewError(null) }} disabled={testing} placeholder="输入包含术语的问题" className="min-h-28 rounded-lg border-transparent bg-[var(--settings-value)] text-base leading-6 focus-visible:border-input sm:text-[14px]" />
              {glossaryDirty ? <p className="text-[13px] leading-6 text-muted-foreground">先保存术语词库，再测试。</p> : null}
              <Button type="submit" variant="outline" className={secondaryActionClass} disabled={saving || testing || glossaryDirty || !testQuery.trim()}>{testing ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <Search className="size-4" />}{testing ? '正在测试…' : '测试展开'}</Button>
            </form>
            <FeedbackToast type="error" message={previewError} id="industry-preview-feedback" />
            {currentPreview ? (
              <div className={styles.rulePreview} aria-live="polite">
                <h4 className="text-[14px] font-semibold">{currentPreview.changed ? '已补充检索词' : '未命中词库中的术语'}</h4>
                <div className="mt-4 text-[13px] leading-6">
                  <p className="text-muted-foreground">原问题</p><p className="mt-1 break-words">{currentPreview.original_query}</p>
                  <ArrowRight aria-hidden="true" className="my-3 size-4 rotate-90 text-muted-foreground" />
                  <p className="text-muted-foreground">检索表达</p><p className="mt-1 break-words font-medium">{currentPreview.expanded_query}</p>
                </div>
              </div>
            ) : null}
          </aside>
        </div>
      )}
    </section>
  )
}
