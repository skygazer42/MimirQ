'use client'

import { useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight,
  BookOpenText,
  Braces,
  CheckCircle2,
  ExternalLink,
  FileText,
  GitBranch,
  Loader2,
  RefreshCw,
  Save,
  Sparkles,
  WandSparkles,
} from 'lucide-react'
import { toast } from 'sonner'

import { Link } from '@/i18n/navigation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { settingsTextTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'
import { industryRulesApi, type IndustryRulesRewritePreviewResponse } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise } from '@/lib/utils'

type ResultState = {
  title: string
  payload: unknown
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function parseJson<T>(raw: string, fallback: T): T {
  const trimmed = raw.trim()
  if (!trimmed) return fallback
  return JSON.parse(trimmed) as T
}

function isRewritePreview(payload: unknown): payload is IndustryRulesRewritePreviewResponse {
  return Boolean(
    payload &&
      typeof payload === 'object' &&
      'original_query' in payload &&
      'expanded_query' in payload &&
      'changed' in payload
  )
}

export function IndustryRulesSection() {
  const queryClient = useQueryClient()
  const [rulesetName, setRulesetName] = useState('industrial_control')
  const [query, setQuery] = useState('PLC 报警如何排查？')
  const [glossaryJson, setGlossaryJson] = useState('{}')
  const [patternsJson, setPatternsJson] = useState('[]')
  const [intentsJson, setIntentsJson] = useState('[]')
  const [runningKey, setRunningKey] = useState<string | null>(null)
  const [result, setResult] = useState<ResultState | null>(null)

  const rulesetsQuery = useQuery({
    queryKey: queryKeys.industryRules.rulesets,
    queryFn: () => industryRulesApi.listRulesets(),
  })
  const rulesets = rulesetsQuery.data?.rulesets || []
  const trimmedRulesetName = rulesetName.trim()
  const selectedRulesetSummary = rulesets.find((item) => item.name === trimmedRulesetName)
  const rulesetDetailQuery = useQuery({
    queryKey: queryKeys.industryRules.ruleset(trimmedRulesetName),
    queryFn: () => industryRulesApi.getRuleset(trimmedRulesetName),
    enabled: false,
  })
  const loadedRuleset = rulesetDetailQuery.data?.ruleset
  const previewResult = result && isRewritePreview(result.payload) ? result.payload : null

  async function runAction(
    key: string,
    title: string,
    action: () => Promise<unknown>,
    options?: { silentSuccess?: boolean }
  ): Promise<void> {
    setRunningKey(key)
    try {
      const payload = await action()
      setResult({ title, payload })
      if (!options?.silentSuccess) toast.success(`${title}完成`)
    } catch (error) {
      toast.error(formatApiError(error, `${title}失败`))
    } finally {
      setRunningKey(null)
    }
  }

  async function loadRulesets(options?: { silentSuccess?: boolean }): Promise<void> {
    await runAction('list', '加载规则集', async () => {
      const { data, error } = await rulesetsQuery.refetch()
      if (error) throw error
      const payload = data || { rulesets: [] }
      const first = payload.rulesets?.[0]?.name
      if (first && !rulesetName.trim()) setRulesetName(first)
      return payload
    }, options)
  }

  const actionDisabled = Boolean(runningKey) || !rulesetName.trim()
  const actionButtonClass = 'h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold'

  return (
    <section>
      <div className={cn(systemWorkbenchTokens.panel, 'space-y-3.5 border-info/15 bg-info/[0.025] p-3.5')}>
        <div className="rounded-lg border border-info/20 bg-info/[0.04] p-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <div className={cn(settingsTextTokens.panelTitle, 'flex items-center gap-1.5')}>
                  <WandSparkles className="h-4 w-4 text-info" />
                  查询改写规则
                </div>
                <div className={settingsTextTokens.sectionBadge}>
                  后端规则接口
                </div>
                <Button asChild variant="outline" className="h-7 gap-1.5 rounded-lg px-2.5 text-[11px] font-semibold">
                  <Link href="/governance/industry-rules">
                    打开完整工作台
                    <ExternalLink className="h-3.5 w-3.5" />
                  </Link>
                </Button>
              </div>
              <p className={cn(settingsTextTokens.helpText, 'mt-1 max-w-2xl')}>
                维护行业术语、匹配规则和意图规则，用来把用户问题补全成更适合检索的表达保存前可以先运行预览，确认改写结果
              </p>
            </div>
            <div className="grid grid-cols-3 gap-1.5 text-center sm:min-w-[270px]">
              <RuleMetric label="术语" value={loadedRuleset?.glossary_count ?? selectedRulesetSummary?.glossary_count ?? '—'} />
              <RuleMetric label="匹配" value={loadedRuleset?.pattern_count ?? selectedRulesetSummary?.pattern_count ?? '—'} />
              <RuleMetric label="意图" value={loadedRuleset?.intent_count ?? selectedRulesetSummary?.intent_count ?? '—'} />
            </div>
          </div>
        </div>

        <div className="grid gap-3 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="space-y-2 rounded-lg border border-border/70 bg-muted/10 p-3">
            <Label htmlFor="industry-rules-name" className={settingsTextTokens.fieldLabel}>
              规则集
            </Label>
            <div className="flex gap-2">
              <Input
                id="industry-rules-name"
                value={rulesetName}
                onChange={(event) => setRulesetName(event.target.value)}
                className="h-8 text-xs"
              />
              <Button
                variant="outline"
                className="h-8 shrink-0 gap-1.5 rounded-lg px-3 text-xs font-semibold"
                disabled={actionDisabled}
                onClick={() =>
                  detachPromise(
                    runAction('detail', '载入规则', async () => {
                      const { data, error } = await rulesetDetailQuery.refetch()
                      if (error) throw error
                      const payload = data || { ruleset: { glossary: {}, patterns: [], intents: [] } }
                      setGlossaryJson(prettyJson(payload.ruleset.glossary || {}))
                      setPatternsJson(prettyJson(payload.ruleset.patterns || []))
                      setIntentsJson(prettyJson(payload.ruleset.intents || []))
                      return payload
                    })
                  )
                }
              >
                {runningKey === 'detail' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <FileText className="h-3.5 w-3.5" />}
                载入
              </Button>
            </div>
            {rulesets.length ? (
              <div className="flex flex-wrap gap-1">
                {rulesets.slice(0, 6).map((item) => (
                  <button
                    key={item.name}
                    type="button"
                    className={cn(
                      'rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors',
                      item.name === trimmedRulesetName
                        ? 'border-info/25 bg-info/10 text-info'
                        : 'border-info/15 bg-info/[0.025] text-muted-foreground hover:border-info/25 hover:text-info'
                    )}
                    onClick={() => setRulesetName(item.name)}
                  >
                    {item.name}
                  </button>
                ))}
              </div>
            ) : (
              <Button
                variant="outline"
                className={actionButtonClass}
                disabled={Boolean(runningKey)}
                onClick={() => detachPromise(loadRulesets())}
              >
                {runningKey === 'list' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <RefreshCw className="h-3.5 w-3.5" />}
                获取规则集
              </Button>
            )}
          </div>

          <div className="space-y-2 rounded-lg border border-border/70 bg-muted/10 p-3">
            <Label htmlFor="industry-rules-query" className={settingsTextTokens.fieldLabel}>
              测试问题
            </Label>
            <div className="flex gap-2">
              <Input
                id="industry-rules-query"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="h-8 text-xs"
              />
              <Button
                variant="outline"
                className="h-8 shrink-0 gap-1.5 rounded-lg px-3 text-xs font-semibold"
                disabled={actionDisabled || !query.trim()}
                onClick={() =>
                  detachPromise(
                    runAction('preview', '改写预览', () =>
                      industryRulesApi.previewRewrite({ ruleset: rulesetName.trim(), query: query.trim() })
                    )
                  )
                }
              >
                {runningKey === 'preview' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Sparkles className="h-3.5 w-3.5" />}
                预览
              </Button>
            </div>
            {previewResult ? (
              <div className="rounded-lg border border-info/20 bg-info/[0.035] p-2.5">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 text-[11px] font-semibold text-foreground/78">
                    <CheckCircle2 className={cn('h-3.5 w-3.5', previewResult.changed ? 'text-success' : 'text-muted-foreground')} />
                    {previewResult.changed ? '已命中行业术语' : '未产生改写'}
                  </div>
                  <span className="rounded-full border border-border/60 bg-muted/30 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                    {previewResult.ruleset}
                  </span>
                </div>
                <div className="grid gap-2 text-[11px] md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:items-center">
                  <PreviewText label="原问题" value={previewResult.original_query} />
                  <ArrowRight className="hidden h-4 w-4 text-muted-foreground/45 md:block" />
                  <PreviewText label="检索表达" value={previewResult.expanded_query} accent={previewResult.changed} />
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <div className="grid gap-3 lg:grid-cols-3">
          <JsonField
            icon={<BookOpenText className="h-3.5 w-3.5 text-info" />}
            label="术语词库"
            meta="设备别名、缩写、行业词同义扩展"
            value={glossaryJson}
            onChange={setGlossaryJson}
            actionLabel="保存词库"
            running={runningKey === 'glossary'}
            disabled={actionDisabled}
            onSave={() =>
              detachPromise(
                runAction('glossary', '保存术语词库', () =>
                  industryRulesApi
                    .updateGlossary(trimmedRulesetName, {
                      glossary: parseJson<Record<string, string[]>>(glossaryJson, {}),
                    })
                    .then((payload) => {
                      queryClient.invalidateQueries({
                        queryKey: queryKeys.industryRules.ruleset(trimmedRulesetName),
                      })
                      return payload
                    })
                )
              )
            }
          />
          <JsonField
            icon={<Braces className="h-3.5 w-3.5 text-info" />}
            label="匹配规则"
            meta="识别报警码、设备类型或固定表达"
            value={patternsJson}
            onChange={setPatternsJson}
            actionLabel="保存规则"
            running={runningKey === 'patterns'}
            disabled={actionDisabled}
            onSave={() =>
              detachPromise(
                runAction('patterns', '保存匹配规则', () =>
                  industryRulesApi
                    .updatePatterns(trimmedRulesetName, {
                      patterns: parseJson<Array<Record<string, unknown>>>(patternsJson, []),
                    })
                    .then((payload) => {
                      queryClient.invalidateQueries({
                        queryKey: queryKeys.industryRules.ruleset(trimmedRulesetName),
                      })
                      return payload
                    })
                )
              )
            }
          />
          <JsonField
            icon={<GitBranch className="h-3.5 w-3.5 text-info" />}
            label="意图规则"
            meta="把问题归到诊断、查询、对比等场景"
            value={intentsJson}
            onChange={setIntentsJson}
            actionLabel="保存意图"
            running={runningKey === 'intents'}
            disabled={actionDisabled}
            onSave={() =>
              detachPromise(
                runAction('intents', '保存意图规则', () =>
                  industryRulesApi
                    .updateIntents(trimmedRulesetName, {
                      intents: parseJson<Array<Record<string, unknown>>>(intentsJson, []),
                    })
                    .then((payload) => {
                      queryClient.invalidateQueries({
                        queryKey: queryKeys.industryRules.ruleset(trimmedRulesetName),
                      })
                      return payload
                    })
                )
              )
            }
          />
        </div>

        <OperationResultPanel title="执行结果" result={result} emptyMessage="载入规则、运行预览或保存后，这里会保留本次接口结果" />
      </div>
    </section>
  )
}

function RuleMetric({ label, value }: Readonly<{ label: string; value: number | string }>) {
  return (
    <div className="rounded-lg border border-info/20 bg-info/[0.035] px-2 py-1.5">
      <div className="text-[14px] font-semibold text-foreground">{value}</div>
      <div className="text-[10px] font-medium text-muted-foreground">{label}</div>
    </div>
  )
}

function PreviewText({
  label,
  value,
  accent,
}: Readonly<{
  label: string
  value: string
  accent?: boolean
}>) {
  return (
    <div className={cn('rounded-md border px-2 py-1.5', accent ? 'border-info/20 bg-info/[0.07]' : 'border-info/15 bg-info/[0.025]')}>
      <div className="mb-0.5 text-[10px] font-semibold text-muted-foreground">{label}</div>
      <div className="break-words text-[11px] leading-4 text-foreground/82">{value}</div>
    </div>
  )
}

function JsonField({
  icon,
  label,
  meta,
  value,
  onChange,
  actionLabel,
  running,
  disabled,
  onSave,
}: Readonly<{
  icon: ReactNode
  label: string
  meta: string
  value: string
  onChange: (next: string) => void
  actionLabel: string
  running: boolean
  disabled: boolean
  onSave: () => void
}>) {
  return (
    <div className="space-y-2 rounded-lg border border-border/70 bg-muted/10 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <Label className={cn(settingsTextTokens.panelTitle, 'flex items-center gap-1.5')}>
            {icon}
            {label}
            <span className="rounded-full border border-info/15 bg-info/[0.035] px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
              JSON
            </span>
          </Label>
          <div className={cn(settingsTextTokens.helpText, 'mt-1')}>{meta}</div>
        </div>
        <Button
          variant="outline"
          className="h-7 shrink-0 gap-1 rounded-md px-2 text-[11px] font-semibold"
          disabled={disabled}
          onClick={onSave}
        >
          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Save className="h-3.5 w-3.5" />}
          {actionLabel}
        </Button>
      </div>
      <Textarea value={value} onChange={(event) => onChange(event.target.value)} className="min-h-[132px] font-mono text-xs" />
    </div>
  )
}
