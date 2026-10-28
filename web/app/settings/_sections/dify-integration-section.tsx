'use client'

import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Copy, RefreshCw, Trash2 } from '@/components/icons'

import { SettingsSwitch } from '@/components/settings/settings-switch'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { settingsLayoutTokens, settingsTextTokens } from '@/components/ui/system-page-tokens'
import { datasetApi, type SystemSettings } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { Dataset } from '@/types'
import styles from '../settings.module.css'

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
  const chars = Array.from(value.toLowerCase())
  const normalized = chars.map((char) => /[a-z0-9\u4e00-\u9fa5]/u.test(char) ? char : '_').join('')
  return normalized.split('_').filter(Boolean).join('_').slice(0, 36) || 'dataset'
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
    setOrigin(globalThis.window.location.origin)
  }, [])

  useEffect(() => {
    let cancelled = false
    async function loadDatasets() {
      setDatasetsLoading(true)
      setDatasetsError('')
      try {
        const items = await datasetApi.listAll()
        if (cancelled) return
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
    globalThis.setTimeout(() => setCopied(false), 1200)
  }

  const inputClassName = cn(
    settingsLayoutTokens.input,
    'border-transparent bg-[var(--settings-value)] placeholder:text-muted-foreground focus-visible:border-input'
  )

  return (
    <div>
      <div className={styles.integrationToggle}>
        <label htmlFor="dify-enabled" className={settingsTextTokens.panelTitle}>
          启用 Dify 接入
        </label>
        <p className={cn(settingsTextTokens.helpText, styles.integrationToggleHint)}>
          允许 Dify 检索已绑定的数据集
        </p>
        <div className={cn(styles.integrationToggleStatus, 'flex shrink-0 items-center gap-3 text-[13px] text-muted-foreground')}>
          <span>{difyExternalKnowledge.enabled ? '已启用' : '未启用'}</span>
          <SettingsSwitch
            id="dify-enabled"
            checked={Boolean(difyExternalKnowledge.enabled)}
            onClick={() => updateDifyExternalKnowledge({ enabled: !difyExternalKnowledge.enabled })}
            aria-label="切换 Dify 外部知识库接入"
          />
        </div>
      </div>

      <div className={styles.integrationLayout}>
        <div className={styles.integrationMain}>
          <section aria-labelledby="dify-connection-title" className={styles.integrationGroup}>
            <h3 id="dify-connection-title" className={styles.integrationTitle}>连接配置</h3>
            <div className="mt-5 space-y-5">
              <div className="min-w-0">
                <div id="dify-endpoint-label" className={styles.integrationLabel}>检索接入地址</div>
                <div className={styles.integrationEndpoint}>
                  <code aria-labelledby="dify-endpoint-label">{endpointUrl || endpointPath}</code>
                  <Button
                    type="button"
                    variant="ghost"
                    className="h-11 shrink-0 gap-1.5 px-2 text-[13px] sm:h-9"
                    onClick={copyEndpoint}
                    aria-label="复制检索地址"
                  >
                    {copied ? <CheckCircle2 className="size-3.5" /> : <Copy className="size-3.5" />}
                    {copied ? '已复制' : '复制'}
                  </Button>
                </div>
              </div>
              <div>
                <label htmlFor="dify-api-key" className={styles.integrationLabel}>API Key</label>
                <Input
                  id="dify-api-key"
                  type="password"
                  value={difyExternalKnowledge.api_keys || ''}
                  placeholder="Dify Bearer Token"
                  className={cn(inputClassName, 'mt-2')}
                  onChange={(event) => updateDifyExternalKnowledge({ api_keys: event.target.value })}
                />
              </div>
            </div>
          </section>

          <section aria-labelledby="dify-datasets-title" className={styles.integrationGroup}>
            <h3 id="dify-datasets-title" className={styles.integrationTitle}>数据集绑定</h3>
            <p className={cn(settingsTextTokens.helpText, 'mt-1')}>
              将一个或多个数据集绑定到 Dify 使用的知识库标识
            </p>

            <div className="mt-5">
              <div className="mb-2 flex items-center justify-between gap-3">
                <span id="dify-dataset-label" className={styles.integrationLabel}>选择数据集</span>
                <span className="text-[13px] tabular-nums text-muted-foreground" aria-live="polite">
                  已选 {selectedDatasetIds.length} 项
                </span>
              </div>
              <div
                role="group"
                aria-labelledby="dify-dataset-label"
                className="max-h-64 divide-y divide-border/60 overflow-auto"
              >
                {datasetsLoading ? (
                  <div role="status" className="flex items-center gap-2 py-3 text-[13px] text-muted-foreground">
                    <RefreshCw className="size-3.5 animate-spin" />
                    正在加载数据集
                  </div>
                ) : null}
                {datasetsError ? (
                  <div role="alert" className="py-3 text-[13px] text-warning">{datasetsError}</div>
                ) : null}
                {!datasetsLoading && datasets.length === 0 && !datasetsError ? (
                  <div className="py-3 text-[13px] text-muted-foreground">暂无可绑定数据集</div>
                ) : null}
                {datasets.map((dataset) => {
                  const checked = selectedDatasetIds.includes(dataset.id)
                  return (
                    <label
                      key={dataset.id}
                      className={cn(
                        'flex min-h-11 w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-3 text-left transition-colors focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ring',
                        checked ? 'bg-[var(--settings-value)] text-foreground' : 'text-foreground hover:bg-muted/30'
                      )}
                    >
                      <Checkbox
                        checked={checked}
                        onCheckedChange={() => toggleDataset(dataset.id)}
                        aria-label={dataset.name}
                      />
                      <span className="min-w-0">
                        <span className="block break-words text-[14px] font-medium [overflow-wrap:anywhere]">{dataset.name}</span>
                        <span className="mt-0.5 block font-mono text-xs text-muted-foreground" title={dataset.id}>
                          {shortId(dataset.id)}
                        </span>
                      </span>
                    </label>
                  )
                })}
              </div>
            </div>

            <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="min-w-0 flex-1">
                <label htmlFor="dify-knowledge-id" className={styles.integrationLabel}>
                  知识库标识 <span className="ml-1 font-mono text-[13px] font-normal text-muted-foreground">knowledge_id</span>
                </label>
                <Input
                  id="dify-knowledge-id"
                  aria-label="knowledge_id"
                  value={knowledgeId}
                  className={cn(inputClassName, 'mt-2 font-mono')}
                  placeholder="knowledge_id"
                  onChange={(event) => setKnowledgeId(event.target.value)}
                />
              </div>
              <Button
                type="button"
                className="h-11 shrink-0 rounded-lg px-4 text-[14px] font-medium sm:h-10"
                disabled={selectedDatasetIds.length === 0}
                onClick={writeBinding}
              >
                生成绑定
              </Button>
            </div>

            <div className="mt-7 border-t border-border/60 pt-5">
              <div className="flex items-center gap-3">
                <h4 className={styles.integrationLabel}>已有绑定</h4>
                {Object.keys(knowledgeMap).length > 0 ? (
                  <span className="text-[13px] tabular-nums text-muted-foreground">{Object.keys(knowledgeMap).length} 条</span>
                ) : null}
              </div>
              {knowledgeMapError ? (
                <div role="alert" className="mt-3 text-[13px] text-warning">{knowledgeMapError}</div>
              ) : null}
              {!knowledgeMapError && Object.keys(knowledgeMap).length === 0 ? (
                <p className="mt-3 text-[13px] text-muted-foreground">尚未创建绑定</p>
              ) : null}
              <div className="mt-2 divide-y divide-border/60">
                {Object.entries(knowledgeMap).map(([bindingId, datasetIds]) => (
                  <div key={bindingId} className="flex items-start justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <div className="break-all font-mono text-[13px] font-medium text-foreground">{bindingId}</div>
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                        {datasetIds.map((datasetId) => (
                          <span key={datasetId} className="break-words text-[13px] leading-5 text-muted-foreground [overflow-wrap:anywhere]">
                            {datasetLabel(datasets.find((dataset) => dataset.id === datasetId), datasetId)}
                          </span>
                        ))}
                      </div>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      className="size-11 shrink-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive sm:size-9"
                      onClick={() => removeBinding(bindingId)}
                      aria-label={`删除 ${bindingId} 绑定`}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          </section>
        </div>

        <section aria-labelledby="dify-request-title" className={styles.integrationAside}>
          <h3 id="dify-request-title" className={styles.integrationTitle}>请求设置</h3>
          <div className="mt-5 space-y-5">
            <div>
              <label htmlFor="dify-account" className={styles.integrationLabel}>服务账号</label>
              <Input
                id="dify-account"
                value={difyExternalKnowledge.account_id || 'system:dify'}
                className={cn(inputClassName, 'mt-2')}
                onChange={(event) => updateDifyExternalKnowledge({ account_id: event.target.value })}
              />
            </div>
            <div>
              <label htmlFor="dify-top-k" className={styles.integrationLabel}>最大返回条数</label>
              <div className="mt-2 flex items-center gap-3">
                <Input
                  id="dify-top-k"
                  type="number"
                  min={1}
                  max={200}
                  value={difyExternalKnowledge.top_k_max}
                  className={cn(inputClassName, 'max-w-28 tabular-nums')}
                  onChange={(event) =>
                    updateDifyExternalKnowledge({
                      top_k_max: Math.max(1, Math.min(200, Number.parseInt(event.target.value || '50', 10))),
                    })
                  }
                />
                <span className="text-[13px] text-muted-foreground">条</span>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
