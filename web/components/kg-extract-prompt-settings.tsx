'use client'

import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { ChevronDown, RefreshCw, Save } from 'lucide-react'

import { settingsApi, type KGConfig, type PromptTemplate } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

const DEFAULT_KG_CONFIG: KGConfig = {
  chat_enabled: false,
  extract_prompt_template_id: '',
  extract_prompt_template_key: '',
  extract_prompt_ab_experiment_key: '',
  extract_replace_existing: true,
  extract_prune_orphan_entities: true,
}

const SELECT_DEFAULT_VALUE = '__mimirq_default__'

export function KgExtractPromptSettings({ templates }: Readonly<{ templates: PromptTemplate[] }>) {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)

  const [original, setOriginal] = useState<KGConfig>(DEFAULT_KG_CONFIG)
  const [draft, setDraft] = useState<KGConfig>(DEFAULT_KG_CONFIG)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      setLoading(true)
      try {
        const settings = await settingsApi.get()
        const next = settings.kg || DEFAULT_KG_CONFIG
        if (cancelled) return
        setOriginal(next)
        setDraft(next)
      } catch (err) {
        console.error(err)
        toast.error(formatApiError(err, '加载 KG 配置失败'))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [])

  const hasChanges = useMemo(() => {
    return JSON.stringify(original) !== JSON.stringify(draft)
  }, [original, draft])

  const save = async () => {
    setSaving(true)
    try {
      const res = await settingsApi.update({ kg: draft })
      toast.success(res.message || '已保存')
      const next = await settingsApi.get()
      setOriginal(next.kg || DEFAULT_KG_CONFIG)
      setDraft(next.kg || DEFAULT_KG_CONFIG)
    } catch (err: any) {
      toast.error(formatApiError(err, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const reset = () => setDraft(original)

  const onPickTemplate = (templateId: string) => {
    setDraft((prev) => ({
      ...prev,
      extract_prompt_template_id: templateId,
      // If a template is pinned by id, clear other selectors to avoid confusion.
      extract_prompt_template_key: templateId ? '' : prev.extract_prompt_template_key,
      extract_prompt_ab_experiment_key: templateId ? '' : prev.extract_prompt_ab_experiment_key,
    }))
  }

  const templatesById = useMemo(() => {
    const map = new Map<string, PromptTemplate>()
    for (const t of templates || []) map.set(t.id, t)
    return map
  }, [templates])

  const pinnedName = useMemo(() => {
    if (!draft.extract_prompt_template_id) return ''
    return templatesById.get(draft.extract_prompt_template_id)?.name || draft.extract_prompt_template_id
  }, [draft.extract_prompt_template_id, templatesById])

  return (
    <Card className={cn('overflow-hidden rounded-xl border-slate-200/80 bg-white shadow-none', loading ? 'opacity-60' : '')}>
      <CardHeader className="space-y-1 border-b border-slate-100 bg-slate-50/70 p-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-[13px] font-semibold text-slate-950">KG 抽取绑定</CardTitle>
          <span className="rounded-full border border-blue-100 bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-600">
            抽取策略
          </span>
        </div>
        <CardDescription className="text-[11px] leading-4 text-slate-500">
          为 KG 抽取和对话召回选择稳定模板；默认使用系统内置提示词。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 p-3">
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-200/75 bg-white px-3 py-2.5">
            <div className="min-w-0">
              <div className="text-[12px] font-semibold text-slate-800">对话 KG 召回</div>
              <div className="mt-0.5 text-[11px] leading-4 text-slate-500">回答前补充事件摘要，提升跨文档线索覆盖。</div>
            </div>
            <Switch
              checked={draft.chat_enabled}
              onCheckedChange={(checked) => setDraft((prev) => ({ ...prev, chat_enabled: checked }))}
            />
          </div>

          <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-200/75 bg-white px-3 py-2.5">
            <div className="min-w-0">
              <div className="text-[12px] font-semibold text-slate-800">重复抽取覆盖旧事件</div>
              <div className="mt-0.5 text-[11px] leading-4 text-slate-500">同一文档重新处理时保持 KG 事件不重复。</div>
            </div>
            <Switch
              checked={draft.extract_replace_existing}
              onCheckedChange={(checked) => setDraft((prev) => ({ ...prev, extract_replace_existing: checked }))}
            />
          </div>

          <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-200/75 bg-white px-3 py-2.5">
            <div className="min-w-0">
              <div className="text-[12px] font-semibold text-slate-800">自动清理孤立实体</div>
              <div className="mt-0.5 text-[11px] leading-4 text-slate-500">事件变更后移除没有关联关系的实体。</div>
            </div>
            <Switch
              checked={draft.extract_prune_orphan_entities}
              onCheckedChange={(checked) => setDraft((prev) => ({ ...prev, extract_prune_orphan_entities: checked }))}
            />
          </div>
        </div>

        <div className="space-y-2 rounded-lg border border-slate-200/75 bg-slate-50/60 p-3">
          <div>
            <Label className="text-[11px] font-semibold text-slate-600">抽取模板</Label>
            <div className="mt-0.5 text-[11px] text-slate-500">固定一个已启用模板，或使用系统默认模板。</div>
          </div>
          <Select
            value={draft.extract_prompt_template_id || SELECT_DEFAULT_VALUE}
            onValueChange={(v) => onPickTemplate(v === SELECT_DEFAULT_VALUE ? '' : v)}
          >
            <SelectTrigger className="h-9 rounded-lg border-slate-200 bg-white text-[12px]">
              <SelectValue placeholder="默认（内置提示词）" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={SELECT_DEFAULT_VALUE}>默认（内置提示词）</SelectItem>
              {templates.map((t) => (
                <SelectItem key={t.id} value={t.id} disabled={!t.is_active}>
                  {t.name}{t.is_active ? '' : '（已停用）'}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {pinnedName ? (
            <div className="text-[11px] text-slate-500">
              当前模板：{pinnedName}
            </div>
          ) : null}
        </div>

        <button
          type="button"
          className="flex w-full items-center justify-between rounded-lg border border-dashed border-slate-200 bg-white px-3 py-2 text-left text-[12px] font-semibold text-slate-700 transition-colors hover:bg-slate-50"
          onClick={() => setShowAdvanced((value) => !value)}
        >
          <span>高级参数</span>
          <ChevronDown className={cn('size-3.5 text-slate-400 transition-transform', showAdvanced && 'rotate-180')} />
        </button>

        {showAdvanced ? (
          <div className="grid grid-cols-1 gap-3 rounded-lg border border-slate-200/75 bg-slate-50/60 p-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label className="text-[11px] font-medium text-slate-500">模板 key</Label>
              <Input
                value={draft.extract_prompt_template_key}
                placeholder="例如：kg_extract_v1"
                onChange={(e) => {
                  const value = e.target.value
                  setDraft((prev) => ({
                    ...prev,
                    extract_prompt_template_key: value,
                    extract_prompt_template_id: value ? '' : prev.extract_prompt_template_id,
                    extract_prompt_ab_experiment_key: value ? '' : prev.extract_prompt_ab_experiment_key,
                  }))
                }}
                className="h-8 bg-white text-[12px]"
              />
              <div className="text-[11px] text-slate-500">按 key 自动选择最新启用版本。</div>
            </div>

            <div className="space-y-1.5">
              <Label className="text-[11px] font-medium text-slate-500">A/B 实验 key</Label>
              <Input
                value={draft.extract_prompt_ab_experiment_key}
                placeholder="例如：exp_kg_extract_2025w01"
                onChange={(e) => {
                  const value = e.target.value
                  setDraft((prev) => ({
                    ...prev,
                    extract_prompt_ab_experiment_key: value,
                    extract_prompt_template_id: value ? '' : prev.extract_prompt_template_id,
                    extract_prompt_template_key: value ? '' : prev.extract_prompt_template_key,
                  }))
                }}
                className="h-8 bg-white text-[12px]"
              />
              <div className="text-[11px] text-slate-500">用于灰度或实验分流。</div>
            </div>
          </div>
        ) : null}

        <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-3">
          <Button variant="outline" onClick={reset} disabled={!hasChanges || saving || loading} className="h-7 rounded-md px-2.5 text-[11px]">
            <RefreshCw className="mr-1 size-3" />
            重置
          </Button>
          <Button onClick={save} disabled={!hasChanges || saving || loading} className="h-7 rounded-md px-2.5 text-[11px]">
            <Save className="mr-1 size-3" />
            保存
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
