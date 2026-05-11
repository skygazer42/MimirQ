'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText, Loader2, RefreshCw, Save, Sparkles } from 'lucide-react'
import { toast } from 'sonner'

import { Link } from '@/i18n/navigation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { systemPageTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'
import { industryRulesApi } from '@/lib/api'
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

export function IndustryRulesSection() {
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

  async function loadRuleset(): Promise<void> {
    await runAction('detail', '加载规则详情', async () => {
      const payload = await industryRulesApi.getRuleset(rulesetName.trim())
      setGlossaryJson(prettyJson(payload.ruleset.glossary || {}))
      setPatternsJson(prettyJson(payload.ruleset.patterns || []))
      setIntentsJson(prettyJson(payload.ruleset.intents || []))
      return payload
    })
  }

  const actionDisabled = Boolean(runningKey) || !rulesetName.trim()
  const actionButtonClass = 'h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold'

  return (
    <section className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold tracking-[-0.01em] text-foreground">
          <Sparkles className="h-4 w-4 text-info" />
          行业规则与查询改写
        </h2>
        <div className="flex items-center gap-2">
          <Button asChild variant="outline" className="h-8 rounded-lg px-3 text-xs font-semibold">
            <Link href="/governance/industry-rules">打开完整工作台</Link>
          </Button>
          <div className="rounded-full border border-info/20 bg-info/10 px-2 py-0.5 text-[11px] font-semibold text-info">
            industry-rules API
          </div>
        </div>
      </div>

      <div className={cn(systemWorkbenchTokens.panel, 'space-y-3 p-3.5')}>
        <p className={systemPageTokens.subtle}>
          管理后端行业规则集的 glossary / patterns / intents，并在保存前预览 query rewrite 效果。
        </p>

        <div className="grid gap-3 md:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="industry-rules-name" className="text-[11px] font-medium text-muted-foreground">
              Ruleset
            </Label>
            <Input id="industry-rules-name" value={rulesetName} onChange={(event) => setRulesetName(event.target.value)} className="h-8 text-xs" />
            {rulesets.length ? (
              <div className="flex flex-wrap gap-1">
                {rulesets.slice(0, 6).map((item) => (
                  <button
                    key={item.name}
                    type="button"
                    className="rounded-full border border-border/60 bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground"
                    onClick={() => setRulesetName(item.name)}
                  >
                    {item.name}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <div className="space-y-1.5 md:col-span-2">
            <Label htmlFor="industry-rules-query" className="text-[11px] font-medium text-muted-foreground">
              Preview Query
            </Label>
            <Input id="industry-rules-query" value={query} onChange={(event) => setQuery(event.target.value)} className="h-8 text-xs" />
          </div>
        </div>

        <div className="grid gap-3 lg:grid-cols-3">
          <JsonField label="Glossary JSON" value={glossaryJson} onChange={setGlossaryJson} />
          <JsonField label="Patterns JSON" value={patternsJson} onChange={setPatternsJson} />
          <JsonField label="Intents JSON" value={intentsJson} onChange={setIntentsJson} />
        </div>

        <div className="flex flex-wrap gap-2">
          <Button variant="outline" className={actionButtonClass} disabled={Boolean(runningKey)} onClick={() => detachPromise(loadRulesets())}>
            {runningKey === 'list' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <RefreshCw className="h-3.5 w-3.5" />}
            列表
          </Button>
          <Button variant="outline" className={actionButtonClass} disabled={actionDisabled} onClick={() => detachPromise(loadRuleset())}>
            <FileText className="h-3.5 w-3.5" />
            详情
          </Button>
          <Button
            variant="outline"
            className={actionButtonClass}
            disabled={actionDisabled || !query.trim()}
            onClick={() =>
              detachPromise(
                runAction('preview', '改写预览', () =>
                  industryRulesApi.previewRewrite({ ruleset: rulesetName.trim(), query: query.trim() })
                )
              )
            }
          >
            <Sparkles className="h-3.5 w-3.5" />
            改写预览
          </Button>
          <Button
            variant="outline"
            className={actionButtonClass}
            disabled={actionDisabled}
            onClick={() =>
              detachPromise(
                runAction('glossary', '保存 glossary', () =>
                  industryRulesApi.updateGlossary(rulesetName.trim(), {
                    glossary: parseJson<Record<string, string[]>>(glossaryJson, {}),
                  })
                )
              )
            }
          >
            <Save className="h-3.5 w-3.5" />
            保存 glossary
          </Button>
          <Button
            variant="outline"
            className={actionButtonClass}
            disabled={actionDisabled}
            onClick={() =>
              detachPromise(
                runAction('patterns', '保存 patterns', () =>
                  industryRulesApi.updatePatterns(rulesetName.trim(), {
                    patterns: parseJson<Array<Record<string, unknown>>>(patternsJson, []),
                  })
                )
              )
            }
          >
            <Save className="h-3.5 w-3.5" />
            保存 patterns
          </Button>
          <Button
            variant="outline"
            className={actionButtonClass}
            disabled={actionDisabled}
            onClick={() =>
              detachPromise(
                runAction('intents', '保存 intents', () =>
                  industryRulesApi.updateIntents(rulesetName.trim(), {
                    intents: parseJson<Array<Record<string, unknown>>>(intentsJson, []),
                  })
                )
              )
            }
          >
            <Save className="h-3.5 w-3.5" />
            保存 intents
          </Button>
        </div>

        <OperationResultPanel title="规则接口结果" result={result} emptyMessage="加载、预览或保存规则后，这里展示执行摘要；原始响应默认收起。" />
      </div>
    </section>
  )
}

function JsonField({
  label,
  value,
  onChange,
}: Readonly<{
  label: string
  value: string
  onChange: (next: string) => void
}>) {
  return (
    <div className="space-y-1.5">
      <Label className="text-[11px] font-medium text-muted-foreground">{label}</Label>
      <Textarea value={value} onChange={(event) => onChange(event.target.value)} className="min-h-[140px] font-mono text-xs" />
    </div>
  )
}
