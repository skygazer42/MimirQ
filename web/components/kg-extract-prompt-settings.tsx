'use client'

import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import { ChevronDown, RefreshCw, Save } from '@/components/icons'

import type { PromptTemplate } from '@/lib/api/prompts'
import { settingsApi } from '@/lib/api/settings'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { KGConfig } from '@/types/settings'

type KgExtractPromptSettingsProps = {
  templates: PromptTemplate[]
}

const SELECT_DEFAULT_VALUE = '__mimirq_default__'

export function KgExtractPromptSettings({ templates }: Readonly<KgExtractPromptSettingsProps>) {
  const [showAdvanced, setShowAdvanced] = useState(false)

  const [draftOverride, setDraftOverride] = useState<KGConfig | null>(null)

  const settingsQuery = useQuery({
    queryKey: queryKeys.settings.snapshot,
    queryFn: ({ signal }) => settingsApi.get({ signal }),
  })

  const original = settingsQuery.data?.kg
  const draft = original === undefined ? undefined : (draftOverride ?? original)
  const loading = settingsQuery.isPending

  const saveMutation = useMutation({
    onMutate: getAuthSessionKey,
    mutationFn: async (next: KGConfig) => {
      const result = await settingsApi.update({ kg: next })
      if (!result.success) throw new Error(result.message)
      return result
    },
    onSuccess: async (res, _draft, sessionKey) => {
      if (sessionKey !== getAuthSessionKey()) return
      toast.success(res.message)
      const refreshed = await settingsQuery.refetch()
      if (refreshed.isSuccess && sessionKey === getAuthSessionKey()) setDraftOverride(null)
    },
    onError: (error, _draft, sessionKey) => {
      if (sessionKey === getAuthSessionKey()) toast.error(formatApiError(error, '保存失败'))
    },
  })
  const saving = saveMutation.isPending

  const updateDraft = (updater: (current: KGConfig) => KGConfig) => {
    if (original === undefined) return
    setDraftOverride((current) => updater(current ?? original))
  }

  const hasChanges = draft !== undefined && JSON.stringify(original) !== JSON.stringify(draft)

  const reset = () => setDraftOverride(null)

  const onPickTemplate = (templateId: string) => {
    updateDraft((prev) => ({
      ...prev,
      extract_prompt_template_id: templateId,
      // If a template is pinned by id, clear other selectors to avoid confusion.
      extract_prompt_template_key: templateId === '' ? prev.extract_prompt_template_key : '',
      extract_prompt_ab_experiment_key: templateId === '' ? prev.extract_prompt_ab_experiment_key : '',
    }))
  }

  const templateId = draft?.extract_prompt_template_id
  const pinnedName =
    templateId === undefined || templateId === ''
      ? undefined
      : (templates.find((template) => template.id === templateId)?.name ?? templateId)

  return (
    <Card className={cn('overflow-hidden rounded-xl border-border/60 bg-card shadow-none', loading && 'opacity-60')}>
      <CardHeader className="space-y-1 border-b border-border/50 bg-muted/40 p-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-[13px] font-semibold text-foreground">KG 抽取绑定</CardTitle>
          <span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
            抽取策略
          </span>
        </div>
        <CardDescription className="text-[11px] leading-4 text-muted-foreground">
          为 KG 抽取和对话召回选择稳定模板；默认使用系统内置提示词。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 p-3">
        {settingsQuery.isError && (
          <div className="flex items-center justify-between gap-2" role="alert">
            <p className="text-xs text-destructive">{formatApiError(settingsQuery.error, '读取 KG 配置失败')}</p>
            <Button type="button" variant="outline" size="sm" onClick={() => void settingsQuery.refetch()}>
              重试
            </Button>
          </div>
        )}
        {draft === undefined ? (
          loading ? (
            <p role="status" className="text-xs text-muted-foreground">
              正在读取 KG 配置…
            </p>
          ) : null
        ) : (
          <fieldset disabled={saving} className="min-w-0 space-y-3" aria-label="KG 抽取设置">
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-card px-3 py-2.5">
                <div className="min-w-0">
                  <div className="text-[12px] font-semibold text-foreground">对话 KG 召回</div>
                  <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                    回答前补充事件摘要，提升跨文档线索覆盖。
                  </div>
                </div>
                <Switch
                  aria-label="对话 KG 召回"
                  checked={draft.chat_enabled}
                  onCheckedChange={(checked) => updateDraft((prev) => ({ ...prev, chat_enabled: checked }))}
                />
              </div>

              <div className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-card px-3 py-2.5">
                <div className="min-w-0">
                  <div className="text-[12px] font-semibold text-foreground">重复抽取覆盖旧事件</div>
                  <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                    同一文档重新处理时保持 KG 事件不重复。
                  </div>
                </div>
                <Switch
                  aria-label="重复抽取覆盖旧事件"
                  checked={draft.extract_replace_existing}
                  onCheckedChange={(checked) =>
                    updateDraft((prev) => ({
                      ...prev,
                      extract_replace_existing: checked,
                    }))
                  }
                />
              </div>

              <div className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-card px-3 py-2.5">
                <div className="min-w-0">
                  <div className="text-[12px] font-semibold text-foreground">自动清理孤立实体</div>
                  <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                    事件变更后移除没有关联关系的实体。
                  </div>
                </div>
                <Switch
                  aria-label="自动清理孤立实体"
                  checked={draft.extract_prune_orphan_entities}
                  onCheckedChange={(checked) =>
                    updateDraft((prev) => ({
                      ...prev,
                      extract_prune_orphan_entities: checked,
                    }))
                  }
                />
              </div>
            </div>

            <div className="space-y-2 rounded-lg border border-border/60 bg-muted/40 p-3">
              <div>
                <Label htmlFor="kg-extract-template" className="text-[11px] font-semibold text-muted-foreground">
                  抽取模板
                </Label>
                <div className="mt-0.5 text-[11px] text-muted-foreground">固定一个已启用模板，或使用系统默认模板。</div>
              </div>
              <Select
                value={
                  draft.extract_prompt_template_id === '' ? SELECT_DEFAULT_VALUE : draft.extract_prompt_template_id
                }
                onValueChange={(v) => onPickTemplate(v === SELECT_DEFAULT_VALUE ? '' : v)}
              >
                <SelectTrigger id="kg-extract-template" className="h-9 rounded-lg border-border bg-card text-[12px]">
                  <SelectValue placeholder="默认（内置提示词）" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={SELECT_DEFAULT_VALUE}>默认（内置提示词）</SelectItem>
                  {templates.map((t) => (
                    <SelectItem key={t.id} value={t.id} disabled={!t.is_active}>
                      {t.name}
                      {t.is_active ? '' : '（已停用）'}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {pinnedName !== undefined && (
                <div className="text-[11px] text-muted-foreground">当前模板：{pinnedName}</div>
              )}
            </div>

            <button
              type="button"
              aria-expanded={showAdvanced}
              className="flex w-full items-center justify-between rounded-lg border border-dashed border-border bg-card px-3 py-2 text-left text-[12px] font-semibold text-foreground/85 transition-colors hover:bg-muted/50"
              onClick={() => setShowAdvanced((value) => !value)}
            >
              <span>高级参数</span>
              <ChevronDown
                className={cn('size-3.5 text-muted-foreground/70 transition-transform', showAdvanced && 'rotate-180')}
              />
            </button>

            {showAdvanced ? (
              <div className="grid grid-cols-1 gap-3 rounded-lg border border-border/60 bg-muted/40 p-3 md:grid-cols-2">
                <div className="space-y-1.5">
                  <Label className="text-[11px] font-medium text-muted-foreground">模板 key</Label>
                  <Input
                    value={draft.extract_prompt_template_key}
                    placeholder="例如：kg_extract_v1"
                    onChange={(e) => {
                      const value = e.target.value
                      updateDraft((prev) => ({
                        ...prev,
                        extract_prompt_template_key: value,
                        extract_prompt_template_id: value ? '' : prev.extract_prompt_template_id,
                        extract_prompt_ab_experiment_key: value ? '' : prev.extract_prompt_ab_experiment_key,
                      }))
                    }}
                    className="h-8 bg-card text-[12px]"
                  />
                  <div className="text-[11px] text-muted-foreground">按 key 自动选择最新启用版本。</div>
                </div>

                <div className="space-y-1.5">
                  <Label className="text-[11px] font-medium text-muted-foreground">A/B 实验 key</Label>
                  <Input
                    value={draft.extract_prompt_ab_experiment_key}
                    placeholder="例如：exp_kg_extract_2025w01"
                    onChange={(e) => {
                      const value = e.target.value
                      updateDraft((prev) => ({
                        ...prev,
                        extract_prompt_ab_experiment_key: value,
                        extract_prompt_template_id: value ? '' : prev.extract_prompt_template_id,
                        extract_prompt_template_key: value ? '' : prev.extract_prompt_template_key,
                      }))
                    }}
                    className="h-8 bg-card text-[12px]"
                  />
                  <div className="text-[11px] text-muted-foreground">用于灰度或实验分流。</div>
                </div>
              </div>
            ) : null}

            <div className="flex items-center justify-end gap-2 border-t border-border/50 pt-3">
              <Button
                variant="outline"
                onClick={reset}
                disabled={!hasChanges || saving || loading}
                className="h-7 rounded-md px-2.5 text-[11px]"
              >
                <RefreshCw className="mr-1 size-3" />
                重置
              </Button>
              <Button
                onClick={() => saveMutation.mutate(draft)}
                disabled={!hasChanges || saving || loading}
                className="h-7 rounded-md px-2.5 text-[11px]"
              >
                <Save className="mr-1 size-3" />
                保存
              </Button>
            </div>
          </fieldset>
        )}
      </CardContent>
    </Card>
  )
}
