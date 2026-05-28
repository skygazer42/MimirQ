'use client'

import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Copy, Database, KeyRound, Link2, PlugZap, RefreshCw, Trash2 } from 'lucide-react'

import { SettingsSwitch } from '@/components/settings/settings-switch'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { settingsTextTokens } from '@/components/ui/system-page-tokens'
import { datasetApi, type SystemSettings } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { Dataset } from '@/types'

type DifyExternalKnowledgeSettings = NonNullable<SystemSettings['dify_external_knowledge']>

type DifyIntegrationSectionProps = {
  difyExternalKnowledge: DifyExternalKnowledgeSettings
  updateDifyExternalKnowledge: (patch: Partial<DifyExternalKnowledgeSettings>) => void
}

function parseKnowledgeMap(raw: string): Record<string, string[]> {
  if (!raw.trim()) return {}
  const parsed = JSON.parse(raw)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}

  const map: Record<string, string[]> = {}
  for (const [knowledgeId, value] of Object.entries(parsed)) {
    if (typeof value === 'string') {
      map[knowledgeId] = [value]
      continue
    }
    if (Array.isArray(value)) {
      map[knowledgeId] = value
        .map((item) => (typeof item === 'string' ? item : ''))
        .filter(Boolean)
      continue
    }
    if (value && typeof value === 'object') {
      const obj = value as Record<string, unknown>
      const ids = obj.dataset_ids ?? obj.datasets ?? obj.dataset_id
      if (typeof ids === 'string') {
        map[knowledgeId] = [ids]
      } else if (Array.isArray(ids)) {
        map[knowledgeId] = ids
          .map((item) => (typeof item === 'string' ? item : ''))
          .filter(Boolean)
      }
    }
  }
  return map
}

function formatKnowledgeMap(map: Record<string, string[]>): string {
  const cleaned: Record<string, string[]> = {}
  for (const [knowledgeId, datasetIds] of Object.entries(map)) {
    const key = knowledgeId.trim()
    const ids = Array.from(new Set(datasetIds.map((id) => id.trim()).filter(Boolean)))
    if (key && ids.length > 0) cleaned[key] = ids
  }
  return Object.keys(cleaned).length ? JSON.stringify(cleaned) : ''
}

function shortId(value: string): string {
  return value.length > 10 ? `${value.slice(0, 8)}…` : value
}

function slugify(value: string): string {
  return (
    value
      .toLowerCase()
      .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 36) || 'dataset'
  )
}

function buildKnowledgeId(datasets: Dataset[]): string {
  if (datasets.length === 1) return `kb_${slugify(datasets[0].name)}`
  if (datasets.length > 1) return `kb_${datasets.length}_datasets`
  return 'kb_default'
}

function datasetLabel(dataset: Dataset | undefined, datasetId: string): string {
  if (!dataset) return shortId(datasetId)
  return `${dataset.name} [${shortId(dataset.id)}]`
}

export function DifyIntegrationSection({
  difyExternalKnowledge,
  updateDifyExternalKnowledge,
}: Readonly<DifyIntegrationSectionProps>) {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>([])
  const [knowledgeId, setKnowledgeId] = useState('kb_default')
  const [datasetsError, setDatasetsError] = useState('')
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const [origin, setOrigin] = useState('')
  const [copied, setCopied] = useState(false)

  const endpointPath = difyExternalKnowledge.endpoint_path || '/api/v1/integrations/dify/retrieval'
  const endpointUrl = `${origin}${endpointPath}`

  let knowledgeMap: Record<string, string[]> = {}
  let knowledgeMapError = ''
  try {
    knowledgeMap = parseKnowledgeMap(difyExternalKnowledge.knowledge_map_json || '')
  } catch {
    knowledgeMapError = '当前绑定配置不是有效 JSON，可重新生成绑定覆盖'
  }

  const selectedDatasets = useMemo(
    () => datasets.filter((dataset) => selectedDatasetIds.includes(dataset.id)),
    [datasets, selectedDatasetIds]
  )

  useEffect(() => {
    setOrigin(window.location.origin)
  }, [])

  useEffect(() => {
    let cancelled = false
    async function loadDatasets() {
      setDatasetsLoading(true)
      setDatasetsError('')
      try {
        const res = await datasetApi.list({ limit: 200 })
        if (cancelled) return
        const items = Array.isArray(res.items) ? res.items : []
        setDatasets(items)
        setSelectedDatasetIds((prev) => prev.filter((id) => items.some((dataset) => dataset.id === id)))
      } catch {
        if (!cancelled) setDatasetsError('数据集加载失败，请刷新后重试')
      } finally {
        if (!cancelled) setDatasetsLoading(false)
      }
    }
    void loadDatasets()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (selectedDatasets.length > 0) setKnowledgeId(buildKnowledgeId(selectedDatasets))
  }, [selectedDatasets])

  const toggleDataset = (datasetId: string) => {
    setSelectedDatasetIds((prev) =>
      prev.includes(datasetId) ? prev.filter((id) => id !== datasetId) : [...prev, datasetId]
    )
  }

  const writeBinding = () => {
    const ids = selectedDatasets.map((dataset) => dataset.id)
    if (ids.length === 0) return
    updateDifyExternalKnowledge({
      knowledge_map_json: formatKnowledgeMap({
        ...knowledgeMap,
        [knowledgeId.trim() || buildKnowledgeId(selectedDatasets)]: ids,
      }),
    })
  }

  const removeBinding = (bindingId: string) => {
    const next = { ...knowledgeMap }
    delete next[bindingId]
    updateDifyExternalKnowledge({ knowledge_map_json: formatKnowledgeMap(next) })
  }

  const copyEndpoint = async () => {
    if (!endpointUrl) return
    await navigator.clipboard?.writeText(endpointUrl)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1200)
  }

  return (
    <section className="space-y-3">
      <div className="rounded-[16px] border border-primary/20 bg-[linear-gradient(135deg,hsl(var(--primary)/0.10),hsl(var(--card)/0.88),hsl(var(--accent)/0.08))] p-3.5">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="flex size-8 items-center justify-center rounded-[12px] border border-primary/20 bg-card/85 text-primary shadow-sm">
                <PlugZap className="size-4" />
              </span>
              <div>
                <h3 className="text-[13px] font-semibold tracking-[-0.01em] text-foreground">
                  Dify 外部知识库
                </h3>
                <p className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                  MimirQ 负责真实召回，Dify 只传 knowledge_id；这里把 knowledge_id 自动绑定到一个或多个数据集
                </p>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-full border border-primary/20 bg-card/80 px-2.5 py-1.5 text-[11px] text-muted-foreground">
            <span>{difyExternalKnowledge.enabled ? '已启用' : '未启用'}</span>
            <SettingsSwitch
              checked={Boolean(difyExternalKnowledge.enabled)}
              onClick={() =>
                updateDifyExternalKnowledge({ enabled: !difyExternalKnowledge.enabled })
              }
              aria-label="切换 Dify 外部知识库接入"
            />
          </div>
        </div>

        <div className="mt-3 grid grid-cols-1 gap-2.5 lg:grid-cols-[minmax(0,1fr)_220px]">
          <div className="rounded-[13px] border border-border/60 bg-foreground px-3 py-2.5 text-background shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-primary-foreground/72">
                  Retrieval Endpoint
                </div>
                <div className="mt-1 truncate font-mono text-[12px] text-background">
                  {endpointUrl || endpointPath}
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                className="h-8 shrink-0 rounded-[11px] border-background/20 bg-background/10 px-2.5 text-[11px] text-background hover:bg-background/18 hover:text-background"
                onClick={copyEndpoint}
              >
                {copied ? <CheckCircle2 className="size-3.5" /> : <Copy className="size-3.5" />}
                复制接入地址
              </Button>
            </div>
          </div>

          <div className="rounded-[13px] border border-border/60 bg-card/85 px-3 py-2.5">
            <div className="flex items-center gap-2 text-[11px] font-medium text-muted-foreground">
              <KeyRound className="size-3.5 text-primary" />
              API Key
            </div>
            <Input
              type="password"
              value={difyExternalKnowledge.api_keys || ''}
              placeholder="Dify Bearer Token"
              className="mt-1.5 h-8 rounded-[10px] border-border/60 bg-background text-[12px]"
              onChange={(event) => updateDifyExternalKnowledge({ api_keys: event.target.value })}
            />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.9fr)]">
        <div className="rounded-[16px] border border-border/60 bg-card/82 p-3.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className={settingsTextTokens.panelTitle}>选择数据集生成绑定</div>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                选择一个或多个数据集后生成 Dify 侧可填写的 knowledge_id
              </div>
            </div>
            <div className="rounded-full border border-border/60 bg-muted/35 px-2.5 py-1 text-[11px] text-muted-foreground">
              已选择数据集 {selectedDatasetIds.length}
            </div>
          </div>

          <div className="mt-3 grid max-h-[260px] grid-cols-1 gap-2 overflow-auto pr-1 md:grid-cols-2">
            {datasetsLoading ? (
              <div className="col-span-full flex items-center gap-2 rounded-[12px] border border-border/60 bg-muted/35 px-3 py-2 text-[12px] text-muted-foreground">
                <RefreshCw className="size-3.5 animate-spin" />
                正在加载数据集
              </div>
            ) : null}
            {datasetsError ? (
              <div className="col-span-full rounded-[12px] border border-warning/25 bg-warning/10 px-3 py-2 text-[12px] text-warning">
                {datasetsError}
              </div>
            ) : null}
            {!datasetsLoading && datasets.length === 0 && !datasetsError ? (
              <div className="col-span-full rounded-[12px] border border-border/60 bg-muted/35 px-3 py-2 text-[12px] text-muted-foreground">
                暂无可绑定数据集
              </div>
            ) : null}
            {datasets.map((dataset) => {
              const checked = selectedDatasetIds.includes(dataset.id)
              return (
                <button
                  key={dataset.id}
                  type="button"
                  aria-pressed={checked}
                  onClick={() => toggleDataset(dataset.id)}
                  className={cn(
                    'flex items-center gap-2 rounded-[12px] border px-3 py-2 text-left transition-colors',
                    checked
                      ? 'border-primary/25 bg-primary/10 text-primary'
                      : 'border-border/60 bg-card text-foreground/78 hover:border-primary/20 hover:bg-primary/8'
                  )}
                >
                  <span
                    className={cn(
                      'flex size-6 shrink-0 items-center justify-center rounded-[9px]',
                      checked ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                    )}
                  >
                    <Database className="size-3.5" />
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-[12px] font-medium">{dataset.name}</span>
                    <span className="block font-mono text-[10.5px] text-muted-foreground">
                      {shortId(dataset.id)}
                    </span>
                  </span>
                </button>
              )
            })}
          </div>

          <div className="mt-3 grid grid-cols-1 gap-2.5 md:grid-cols-[minmax(0,1fr)_auto]">
            <Input
              value={knowledgeId}
              className="h-9 rounded-[11px] border-border/60 bg-background text-[12px]"
              placeholder="knowledge_id"
              onChange={(event) => setKnowledgeId(event.target.value)}
            />
            <Button
              type="button"
              className="h-9 rounded-[11px] bg-primary px-3 text-[12px] font-medium text-primary-foreground hover:bg-primary/90"
              disabled={selectedDatasetIds.length === 0}
              onClick={writeBinding}
            >
              <Link2 className="size-3.5" />
              生成绑定
            </Button>
          </div>
        </div>

        <div className="space-y-3 rounded-[16px] border border-border/60 bg-card/82 p-3.5">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className={settingsTextTokens.panelTitle}>当前绑定</div>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                Dify 请求里的 knowledge_id 会按这里路由到数据集
              </div>
            </div>
            <div className="rounded-full border border-border/60 bg-muted/35 px-2 py-0.5 text-[11px] text-muted-foreground">
              {Object.keys(knowledgeMap).length} 条
            </div>
          </div>

          {knowledgeMapError ? (
            <div className="rounded-[12px] border border-warning/25 bg-warning/10 px-3 py-2 text-[12px] text-warning">
              {knowledgeMapError}
            </div>
          ) : null}

          <div className="space-y-2">
            {Object.entries(knowledgeMap).length === 0 ? (
              <div className="rounded-[13px] border border-dashed border-border/60 bg-muted/35 px-3 py-5 text-center text-[12px] text-muted-foreground">
                暂无绑定选择数据集后生成一个 knowledge_id
              </div>
            ) : null}
            {Object.entries(knowledgeMap).map(([bindingId, datasetIds]) => (
              <div
                key={bindingId}
                className="rounded-[13px] border border-border/60 bg-muted/30 px-3 py-2.5"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-mono text-[12px] font-semibold text-foreground">{bindingId}</div>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {datasetIds.map((datasetId) => (
                        <span
                          key={datasetId}
                          className="rounded-full border border-primary/20 bg-card px-2 py-0.5 text-[10.5px] text-muted-foreground"
                        >
                          {datasetLabel(datasets.find((dataset) => dataset.id === datasetId), datasetId)}
                        </span>
                      ))}
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    className="h-7 w-7 shrink-0 rounded-[9px] text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    onClick={() => removeBinding(bindingId)}
                    aria-label={`删除 ${bindingId} 绑定`}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-1">
            <label className="block text-[11px] leading-4 text-muted-foreground">
              <span className={settingsTextTokens.fieldLabel}>服务账号</span>
              <Input
                value={difyExternalKnowledge.account_id || 'system:dify'}
                className="mt-1 h-8 rounded-[10px] border-border/60 bg-background text-[12px]"
                onChange={(event) => updateDifyExternalKnowledge({ account_id: event.target.value })}
              />
            </label>
            <label className="block text-[11px] leading-4 text-muted-foreground">
              <span className={settingsTextTokens.fieldLabel}>最大返回条数</span>
              <Input
                type="number"
                min={1}
                max={200}
                value={difyExternalKnowledge.top_k_max}
                className="mt-1 h-8 rounded-[10px] border-border/60 bg-background text-[12px]"
                onChange={(event) =>
                  updateDifyExternalKnowledge({
                    top_k_max: Math.max(1, Math.min(200, Number.parseInt(event.target.value || '50', 10))),
                  })
                }
              />
            </label>
          </div>
        </div>
      </div>
    </section>
  )
}
