'use client'

import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { RefreshCw, Save } from 'lucide-react'

import { settingsApi, type KGConfig, type PromptTemplate } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
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
    <Card className={cn(loading ? 'opacity-60' : '')}>
      <CardHeader>
        <CardTitle>KG 抽取提示词配置</CardTitle>
        <CardDescription>
          选择用于“事件/实体抽取”的 PromptTemplate。变量：{`{context}`}（chunk 文本）、{`{schema}`}（JSON schema）。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2">
          <Checkbox
            checked={draft.chat_enabled}
            onCheckedChange={(v) => setDraft((prev) => ({ ...prev, chat_enabled: v === true }))}
          />
          <div className="text-sm">
            <div className="font-medium">对话启用 KG 增强检索</div>
            <div className="text-muted-foreground text-xs">开启后，Chat 会额外召回 KG 事件摘要作为上下文。</div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Checkbox
            checked={draft.extract_replace_existing}
            onCheckedChange={(v) => setDraft((prev) => ({ ...prev, extract_replace_existing: v === true }))}
          />
          <div className="text-sm">
            <div className="font-medium">重复抽取时替换旧事件</div>
            <div className="text-muted-foreground text-xs">避免同一文档/切片重复写入 KG 事件。</div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Checkbox
            checked={draft.extract_prune_orphan_entities}
            onCheckedChange={(v) => setDraft((prev) => ({ ...prev, extract_prune_orphan_entities: v === true }))}
          />
          <div className="text-sm">
            <div className="font-medium">清理孤立实体</div>
            <div className="text-muted-foreground text-xs">替换/删除事件后，自动删除无任何事件关联的实体。</div>
          </div>
        </div>

        <div className="space-y-2">
          <Label>抽取模板（按 ID 固定）</Label>
          <Select
            value={draft.extract_prompt_template_id || SELECT_DEFAULT_VALUE}
            onValueChange={(v) => onPickTemplate(v === SELECT_DEFAULT_VALUE ? '' : v)}
          >
            <SelectTrigger>
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
            <div className="text-xs text-muted-foreground">
              当前固定模板：{pinnedName}
            </div>
          ) : null}
        </div>

        <div className="flex items-center gap-2">
          <Checkbox checked={showAdvanced} onCheckedChange={(v) => setShowAdvanced(v === true)} />
          <div className="text-sm font-medium">高级：按 template_key / A-B 实验选择</div>
        </div>

        {showAdvanced ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>template_key（版本化选择）</Label>
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
              />
              <div className="text-xs text-muted-foreground">取该 key 下 is_active 且版本号最大的模板。</div>
            </div>

            <div className="space-y-2">
              <Label>A/B 实验 key</Label>
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
              />
              <div className="text-xs text-muted-foreground">按 ab_weight 稳定分流（有 account_id 时会用于 seed）。</div>
            </div>
          </div>
        ) : null}

        <div className="flex items-center justify-end gap-2">
          <Button variant="outline" onClick={reset} disabled={!hasChanges || saving || loading}>
            <RefreshCw className="w-4 h-4 mr-2" />
            重置
          </Button>
          <Button onClick={save} disabled={!hasChanges || saving || loading}>
            <Save className="w-4 h-4 mr-2" />
            保存
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

