'use client'

/**
 * KnowledgeSettingsPanel & KnowledgeConnectorRunsPanel
 * 优化版：任务中心极致高密度、UI Pro Max 视觉增强
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Database,
  History,
  Info,
  Link2,
  Loader2,
  RefreshCw,
  RotateCcw,
  Settings,
  Terminal,
  X,
} from 'lucide-react'
import { useTranslations } from 'next-intl'
import { motion, AnimatePresence } from 'framer-motion'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Panel } from '@/components/ui/panel'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Switch } from '@/components/ui/switch'

import {
  datasetApi,
  retrievalApi,
  settingsApi,
  type SystemSettings,
} from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import {
  buildDatasetRagDefaultsForUpdate,
  buildRetrievalConfigHashRequest,
  datasetRagContractModeLabel,
  hasDatasetRagContract,
  mergeDatasetRagDefaultsIntoRagConfig,
} from '@/lib/dataset-rag-contract'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise, formatDate } from '@/lib/utils'
import type { ConnectorRunOut, Dataset } from '@/types'

// --- 类型定义 ---
type KnowledgeSettingsConfig = Pick<SystemSettings, 'embedding' | 'rag'>
type DatasetRagVerificationState = {
  datasetId: string
  hash: string
  effectiveConfig: Record<string, unknown>
  verifiedAt: string
}
type ConnectorRunStatusFilter =
  | 'all'
  | 'pending'
  | 'running'
  | 'failed'
  | 'completed'
  | 'cancelled'
type TranslateValue = string | number | Date
type TranslateFn = (key: string, values?: Record<string, TranslateValue>) => string

type KnowledgeSettingsPanelProps = {
  selectedDatasetId?: string
  selectedDataset?: Dataset | null
  datasets?: Dataset[]
  datasetsLoading?: boolean
  datasetAllValue?: string
  onDatasetScopeChange?: (value: string) => void
  onGoToRetrievalTest?: () => void
  settingsSidebarCollapsed?: boolean
}

type KnowledgeConnectorRunsPanelProps = {
  selectedDatasetId?: string
  connectorRuns: ConnectorRunOut[]
  connectorRunsLoading: boolean
  onCancelConnectorRun: (id: string) => void | Promise<void>
  onResumeConnectorRun: (id: string) => void | Promise<void>
  onRetryFailedConnectorRun: (id: string) => void | Promise<void>
  onLoadConnectorRuns: (params: { datasetId?: string }) => void | Promise<void>
}

type TaskCardProps = {
  run: ConnectorRunOut
  t: TranslateFn
  onCancel: (id: string) => void | Promise<void>
  onResume?: (id: string) => void | Promise<void>
  onRetry: (id: string) => void | Promise<void>
  isExpanded: boolean
  onToggleExpand: () => void
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function getConnectorRunProgress(rawStats: unknown) {
  const stats = isRecord(rawStats) ? rawStats : {}
  const total = Number(
    stats?.total_items || stats?.items_total || stats?.total_urls || 0
  )
  const processed = Number(
    stats?.processed_items ||
      stats?.items_processed ||
      stats?.processed_urls ||
      0
  )
  return { total, processed }
}

function getConnectorRunErrors(stats: unknown): Record<string, unknown>[] {
  const record = isRecord(stats) ? stats : {}
  return Array.isArray(record.errors) ? record.errors.filter(isRecord) : []
}

const EMBEDDING_PRESETS = [
  {
    model: 'text-embedding-v4',
    provider: 'dashscope',
    apiBase: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    brand: 'Qwen Embedding',
  },
  {
    model: 'text-embedding-v3',
    provider: 'dashscope',
    apiBase: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    brand: 'Qwen Embedding',
  },
  {
    model: 'text-embedding-3-small',
    provider: 'openai_compatible',
    apiBase: 'https://api.openai.com/v1',
    brand: 'OpenAI Embedding',
  },
  {
    model: 'bge-large-zh',
    provider: 'local',
    apiBase: '',
    brand: '本地 Embedding',
  },
] as const
type EmbeddingPresetModel = (typeof EMBEDDING_PRESETS)[number]['model']
const SETTINGS_GUIDE_PANEL_ID = 'knowledge-settings-guide'
const SETTINGS_PANEL_CLASS =
  'rounded-xl border border-border/55 bg-background shadow-none backdrop-blur-none dark:border-border/65 dark:bg-background'
const SETTINGS_SIDE_PANEL_CLASS =
  'rounded-none border-0 border-b border-border/50 bg-transparent shadow-none backdrop-blur-none last:border-b-0 dark:border-border/60 dark:bg-transparent'
const SETTINGS_PANEL_HEADER_CLASS = 'border-b border-border/60 px-3 py-2.5 dark:border-border/60'
const SETTINGS_PANEL_ICON_CLASS =
  'relative flex size-7 items-center justify-center rounded-lg border border-border/55 bg-muted/25 text-primary shadow-none'
const SETTINGS_SIDE_ICON_CLASS =
  'relative mt-0.5 flex size-6 items-center justify-center rounded-md border border-border/55 bg-muted/25 text-primary/80 shadow-none dark:border-border/65 dark:bg-muted/10'
const SETTINGS_CONTROL_CLASS =
  'border-border/60 bg-background shadow-none hover:border-primary/25 hover:bg-muted/20 dark:border-border/70 dark:bg-background'
const EMBEDDING_MODEL_META: Record<
  EmbeddingPresetModel,
  { description: string; chips: string[] }
> = {
  'text-embedding-v4': {
    description: '阿里云百炼当前推荐文本向量模型，适合作为中文 RAG 的默认选择。',
    chips: ['Qwen3 向量', '官方推荐', '中文优先'],
  },
  'text-embedding-v3': {
    description: '适合兼容已有百炼 v3 索引或低成本平滑迁移场景。',
    chips: ['Qwen3 向量', '兼容迁移', '中文友好'],
  },
  'text-embedding-3-small': {
    description: '响应更轻量，适合成本敏感或高频检索场景。',
    chips: ['低成本', '响应快', 'OpenAI 兼容'],
  },
  'bge-large-zh': {
    description: '中文语义更强，适合中文知识库和条款型文本。',
    chips: ['中文增强', '本地可部署', '长文本友好'],
  },
}

function normalizeApiBase(value: string | null | undefined): string {
  return String(value || '').trim().toLowerCase()
}

function inferEmbeddingBrand(
  embedding: KnowledgeSettingsConfig['embedding'] | null | undefined
): string {
  if (!embedding) return '未识别'
  const model = String(embedding.model || '').trim().toLowerCase()
  const provider = String(embedding.provider || '').trim().toLowerCase()
  const apiBase = normalizeApiBase(embedding.api_base)

  if (
    provider === 'dashscope' ||
    apiBase.includes('dashscope.aliyuncs.com') ||
    model === 'text-embedding-v4' ||
    model === 'text-embedding-v3'
  ) {
    return 'Qwen Embedding'
  }
  if (provider === 'local' || model === 'bge-large-zh') {
    return '本地 Embedding'
  }
  return 'OpenAI Embedding'
}

function cloneSettingsConfig(
  config: KnowledgeSettingsConfig
): KnowledgeSettingsConfig {
  return structuredClone(config)
}

function buildScopedSettingsConfig(
  settings: SystemSettings,
  selectedDataset?: Dataset | null
): KnowledgeSettingsConfig {
  const datasetEmbedding = selectedDataset?.embedding_defaults
  const datasetRagDefaults = selectedDataset?.rag_defaults
  return {
    embedding: {
      ...settings.embedding,
      provider: datasetEmbedding?.provider || settings.embedding.provider,
      model: datasetEmbedding?.model || settings.embedding.model,
      api_base: datasetEmbedding?.api_base ?? settings.embedding.api_base,
    },
    rag: mergeDatasetRagDefaultsIntoRagConfig(settings.rag, datasetRagDefaults),
  }
}

function buildDatasetEmbeddingDefaults(config: KnowledgeSettingsConfig) {
  return {
    provider: config.embedding.provider,
    model: config.embedding.model,
    api_base: config.embedding.api_base || null,
  }
}

// --- KnowledgeSettingsPanel 实现 ---
export function KnowledgeSettingsPanel({
  selectedDatasetId,
  selectedDataset,
  datasets = [],
  datasetsLoading = false,
  datasetAllValue = '__all__',
  onDatasetScopeChange,
  onGoToRetrievalTest,
  settingsSidebarCollapsed = false,
}: Readonly<KnowledgeSettingsPanelProps>) {
  const t = useTranslations('KnowledgeSettingsPanel')
  const queryClient = useQueryClient()
  // t("connectorRuns.empty.description")
  // t("connectorRuns.zeroState.description")
  // t("dangerZone.trigger")
  // datasetApi.purge
  // dry_run
  // aria-label={t("connectorRuns.filter.ariaLabel")}
  // label: t(`runStatus.${value}`)
  // setRunStatusFilter('all')
  // bg-primary/10 px-2.5 py-0.5 rounded-lg border border-primary/20
  // border-border/40 bg-background/70
  const [draftConfig, setDraftConfig] =
    useState<KnowledgeSettingsConfig | null>(null)
  const [savedConfig, setSavedConfig] =
    useState<KnowledgeSettingsConfig | null>(null)
  const [isSavingSettings, setIsSavingSettings] = useState(false)
  const [confirmEmbeddingSaveOpen, setConfirmEmbeddingSaveOpen] =
    useState(false)
  const [datasetRagVerification, setDatasetRagVerification] =
    useState<DatasetRagVerificationState | null>(null)
  const [guideExpanded, setGuideExpanded] = useState(false)
  const [currentConfigOpen, setCurrentConfigOpen] = useState(false)

  const settingsQuery = useQuery({
    queryKey: queryKeys.settings.snapshot,
    queryFn: () => settingsApi.get(),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  })
  const settingsLoading = settingsQuery.isLoading

  useEffect(() => {
    if (!settingsQuery.data) return
    const cfg = buildScopedSettingsConfig(settingsQuery.data, selectedDataset)
    setSavedConfig(cfg)
    setDraftConfig(cloneSettingsConfig(cfg))
  }, [
    settingsQuery.data,
    selectedDataset,
    selectedDataset?.embedding_defaults?.api_base,
    selectedDataset?.embedding_defaults?.model,
    selectedDataset?.embedding_defaults?.provider,
    selectedDatasetId,
  ])

  useEffect(() => {
    if (!settingsQuery.error) return
    toast.error(formatApiError(settingsQuery.error, t('toasts.loadFailed')))
  }, [settingsQuery.error, t])

  const isDirty = useMemo(
    () => JSON.stringify(savedConfig) !== JSON.stringify(draftConfig),
    [savedConfig, draftConfig]
  )
  const handleResetDraft = useCallback(() => {
    setDraftConfig(savedConfig ? cloneSettingsConfig(savedConfig) : null)
    setConfirmEmbeddingSaveOpen(false)
  }, [savedConfig])

  const handleSave = async () => {
    if (!draftConfig || isSavingSettings) return
    setIsSavingSettings(true)
    try {
      if (selectedDatasetId) {
        const nextRagDefaults = buildDatasetRagDefaultsForUpdate({
          currentDefaults: selectedDataset?.rag_defaults,
          savedRag: savedConfig?.rag ?? draftConfig.rag,
          draftRag: draftConfig.rag,
        })
        await datasetApi.update(selectedDatasetId, {
          embedding_defaults: buildDatasetEmbeddingDefaults(draftConfig),
          rag_defaults: nextRagDefaults ?? undefined,
        })
        const refreshedDataset = await datasetApi.get(selectedDatasetId)
        queryClient.setQueryData(
          queryKeys.datasets.detail(selectedDatasetId),
          refreshedDataset
        )
        await queryClient.invalidateQueries({
          queryKey: queryKeys.datasets.all,
        })
        await queryClient.invalidateQueries({
          queryKey: queryKeys.datasets.exhaustive(),
        })

        const nextConfig = settingsQuery.data
          ? buildScopedSettingsConfig(settingsQuery.data, refreshedDataset)
          : cloneSettingsConfig(draftConfig)
        setSavedConfig(cloneSettingsConfig(nextConfig))
        setDraftConfig(cloneSettingsConfig(nextConfig))

        const hashRequest = buildRetrievalConfigHashRequest(
          refreshedDataset.rag_defaults
        )
        if (hashRequest) {
          const hashResponse = await retrievalApi.configHash(hashRequest)
          setDatasetRagVerification({
            datasetId: selectedDatasetId,
            hash: toTrimmedPrimitiveString(hashResponse.hash),
            effectiveConfig: isRecord(hashResponse.effective_config)
              ? hashResponse.effective_config
              : {},
            verifiedAt: new Date().toISOString(),
          })
          toast.success(
            `已保存并验证数据集契约（cfg ${toTrimmedPrimitiveString(
              hashResponse.hash
            ).slice(0, 12) || '--'}）`
          )
        } else {
          setDatasetRagVerification(null)
          toast.success('已保存到当前数据集；当前未配置 dataset 级检索契约')
        }
      } else {
        await settingsApi.update(draftConfig)
        setSavedConfig(cloneSettingsConfig(draftConfig))
        toast.success(t('toasts.saveSuccess'))
      }
    } catch (err) {
      toast.error(formatApiError(err, t('toasts.saveFailed')))
    } finally {
      setIsSavingSettings(false)
      setConfirmEmbeddingSaveOpen(false)
    }
  }

  const handleSaveDraft = () => {
    if (savedConfig?.embedding.model !== draftConfig?.embedding.model) {
      setConfirmEmbeddingSaveOpen(true)
      return
    }
    detachPromise(handleSave())
  }

  const handleApplyRecommendedConfig = () => {
    setDraftConfig((prev) =>
      prev
        ? {
            ...prev,
            rag: {
              ...prev.rag,
              retrieval_top_k: Math.max(prev.rag.retrieval_top_k, 12),
              similarity_threshold: Math.min(
                prev.rag.similarity_threshold,
                0.6
              ),
            },
          }
        : null
    )
    toast.success('已应用到配置草稿，请保存后生效')
  }

  if (settingsLoading && !draftConfig)
    return (
      <div className="p-8 space-y-4 animate-pulse">
        <div className="h-20 rounded-2xl bg-muted/55" />
        <div className="h-40 rounded-2xl bg-muted/45" />
      </div>
    )

  const isDatasetScoped = Boolean(selectedDatasetId)
  const selectedScopeValue = selectedDatasetId || datasetAllValue
  const selectedDatasetName =
    selectedDataset?.name || selectedDatasetId || '系统默认'
  const currentEmbeddingBrand = inferEmbeddingBrand(savedConfig?.embedding)
  const scopeLabel = isDatasetScoped ? selectedDatasetName : '系统默认'
  const configuredEmbeddingModel = draftConfig?.embedding.model || ''
  const hasCustomEmbeddingModel = Boolean(
    configuredEmbeddingModel &&
      !EMBEDDING_PRESETS.some(
        (preset) => preset.model === configuredEmbeddingModel
      )
  )
  const hasDatasetEmbeddingOverride = Boolean(
    selectedDataset?.embedding_defaults?.model
  )
  const datasetRagContract = selectedDataset?.rag_defaults ?? null
  const datasetRagVerificationForScope =
    datasetRagVerification?.datasetId === selectedDatasetId
      ? datasetRagVerification
      : null
  const canExplainWithDatasetContract =
    Boolean(selectedDatasetId) &&
    (hasDatasetRagContract(datasetRagContract) ||
      Boolean(datasetRagVerificationForScope?.hash))
  const retrievalModeValue =
    draftConfig?.rag.retrieval_mode || savedConfig?.rag.retrieval_mode || 'hybrid'
  const saveScopeDescription = isDatasetScoped
    ? '仅保存到当前数据集；已有文档不会自动重新向量化。'
    : '作为新数据集和未覆盖数据集的默认配置。'
  const embeddingChangeDescription = isDatasetScoped
    ? '这次只更新当前数据集的 embedding 配置，不会改动其他已维护数据集。已有已解析文档不会自动重新嵌入；隔离中的文档保持隔离状态，只有人工释放或显式重新入库时才会进入向量化。'
    : '这次只更新系统默认 embedding 配置，不会自动迁移已有数据集向量。已经设置独立 embedding 的数据集不会被覆盖；隔离中的文档也不会因为默认配置变化而重新嵌入。'
  const retrievalTopK = draftConfig?.rag.retrieval_top_k ?? 5
  const similarityThreshold = draftConfig?.rag.similarity_threshold ?? 0.7
  const ragContractLabel = isDatasetScoped
    ? datasetRagContractModeLabel(datasetRagContract)
    : '全局 API 未暴露检索契约'
  const ragHashLabel = datasetRagVerificationForScope?.hash
    ? `${datasetRagVerificationForScope.hash.slice(0, 12)}…`
    : isDatasetScoped
      ? '未验证'
      : '已禁用'
  const topKTrackPercent = ((retrievalTopK - 1) / (50 - 1)) * 100
  const similarityTrackPercent = similarityThreshold * 100

  return (
    <div
      className="flex h-full min-h-0 flex-col overflow-hidden bg-transparent dark:bg-background/35"
      aria-label={t('header.title')}
    >
      <div className="flex-1 min-h-0 overflow-y-auto p-0 no-scrollbar lg:overflow-y-auto">
        <div
          className={cn(
            'grid min-h-0 gap-0 lg:h-full',
            settingsSidebarCollapsed
              ? 'lg:grid-cols-1'
              : 'lg:grid-cols-[206px_minmax(0,1fr)]'
          )}
        >
          {settingsSidebarCollapsed ? null : (
            <div className="space-y-0 border-r border-border/50 bg-background/45 lg:sticky lg:top-0 lg:self-start dark:border-border/60 dark:bg-background/35">
              <Panel
                padding="none"
                className={SETTINGS_SIDE_PANEL_CLASS}
              >
                <div className="px-3 pt-3">
                  <div className="flex items-start gap-2.5">
                    <div className={SETTINGS_SIDE_ICON_CLASS}>
                      <Database className="size-3" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-[13px] font-medium text-foreground/92">
                        配置范围
                      </div>
                      <div className="mt-1 text-[11px] font-medium leading-4 text-muted-foreground/88">
                        选择配置应用到哪里
                      </div>
                    </div>
                  </div>
                </div>
                <div className="space-y-2.5 p-3 pt-2.5">
                  <div className="space-y-1.5">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/84">
                      选择数据集
                    </div>
                    <Select
                      value={selectedScopeValue}
                      onValueChange={onDatasetScopeChange}
                      disabled={!onDatasetScopeChange || datasetsLoading}
                    >
                      <SelectTrigger
                        className={cn('h-8 rounded-[12px] pl-3 pr-2 text-[11px] transition-colors duration-200 [&>span]:font-medium [&>span]:text-foreground/90 [&>svg]:h-3 [&>svg]:w-3 [&>svg]:text-muted-foreground/65', SETTINGS_CONTROL_CLASS)}
                        aria-label="选择数据集配置作用域"
                      >
                        <SelectValue
                          placeholder={
                            datasetsLoading ? '加载数据集...' : '选择数据集'
                          }
                        />
                      </SelectTrigger>
                      <SelectContent className="rounded-[14px] border-border/70 bg-popover p-1 shadow-[0_18px_42px_-28px_hsl(var(--foreground)/0.36)]">
                        <SelectItem value={datasetAllValue}>
                          系统默认 · 新数据集
                        </SelectItem>
                        {datasets.map((dataset) => (
                          <SelectItem key={dataset.id} value={dataset.id}>
                            {dataset.name} · {dataset.id.slice(0, 8)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {datasets.length === 0 && !datasetsLoading ? (
                      <div className="rounded-[11px] border border-dashed border-border/60 bg-background/52 px-2.5 py-2 text-[11px] font-medium leading-4 text-muted-foreground/84 dark:border-border/70 dark:bg-background/45">
                        暂无可选数据集，可先使用系统默认配置。
                      </div>
                    ) : null}
                  </div>

                  <div className="flex items-center gap-2 text-[10px] font-medium text-muted-foreground/78">
                    <span className="size-1.5 shrink-0 rounded-full bg-info/75" />
                    <span className="truncate">
                      {isDatasetScoped
                        ? `${scopeLabel} · 仅影响后续入库`
                        : '系统默认 · 用于新数据集'}
                    </span>
                  </div>
                </div>
              </Panel>

              <Panel
                padding="none"
                className={SETTINGS_SIDE_PANEL_CLASS}
              >
              <div className="p-3">
                <button
                  type="button"
                  aria-expanded={guideExpanded}
                  aria-controls={SETTINGS_GUIDE_PANEL_ID}
                  onClick={() => setGuideExpanded((expanded) => !expanded)}
                  className="flex w-full items-center justify-between gap-3 text-[11px] font-medium text-foreground transition-colors hover:text-primary"
                >
                  <span className="flex items-center gap-2">
                    <Info className="size-3 text-primary" />
                    参数怎么选？
                  </span>
                  <ChevronRight
                    className={cn(
                      'size-3 text-muted-foreground transition-transform',
                      guideExpanded && 'rotate-90'
                    )}
                  />
                </button>
                {guideExpanded ? (
                  <div
                    id={SETTINGS_GUIDE_PANEL_ID}
                    className="mt-2.5 space-y-1.5 border-l border-primary/25 pl-2.5 text-[10px] font-medium leading-4 text-muted-foreground/82"
                  >
                    <div>中文知识库优先选择中文或多语言模型。</div>
                    <div>Top K 建议 8～20，越高召回越全。</div>
                    <div>相似度阈值建议 0.50～0.80。</div>
                  </div>
                ) : null}
              </div>
              </Panel>

              <Panel
                padding="none"
                className={SETTINGS_SIDE_PANEL_CLASS}
              >
              <div className="p-3">
                <button
                  type="button"
                  aria-expanded={currentConfigOpen}
                  aria-controls="knowledge-current-config-panel"
                  onClick={() => setCurrentConfigOpen((open) => !open)}
                  className="flex w-full items-center justify-between gap-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                >
                  <span className="min-w-0">
                    <span className="block text-[11px] font-medium text-foreground">
                      配置状态
                    </span>
                    <span className="mt-0.5 block truncate text-[10px] text-muted-foreground/72">
                      {savedConfig?.embedding.model || '-'}
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span
                      className={cn(
                        'text-[10px] font-medium',
                        isDirty ? 'text-warning' : 'text-success'
                      )}
                    >
                      {isDirty ? '未保存' : '已同步'}
                    </span>
                    <ChevronDown
                      className={cn(
                        'size-3.5 text-muted-foreground transition-transform duration-200',
                        !currentConfigOpen && '-rotate-90'
                      )}
                    />
                  </span>
                </button>
              </div>
              {currentConfigOpen ? (
                <div
                  id="knowledge-current-config-panel"
                  className="grid gap-2 border-t border-border/45 p-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <span className="text-[10px] text-muted-foreground/72">
                      模型来源
                    </span>
                    <span className="max-w-[8rem] truncate text-right text-[10px] font-medium text-foreground">
                      {currentEmbeddingBrand}
                    </span>
                  </div>
                  <div className="flex items-start justify-between gap-3">
                    <span className="text-[10px] text-muted-foreground/72">
                      RAG 契约
                    </span>
                    <span className="max-w-[8rem] text-right text-[10px] font-medium text-foreground">
                      {ragContractLabel}
                    </span>
                  </div>
                  <div className="flex items-start justify-between gap-3">
                    <span className="text-[10px] text-muted-foreground/72">
                      校验状态
                    </span>
                    <span className="max-w-[8rem] text-right">
                      <span className="block truncate font-mono text-[10px] text-foreground">
                        {ragHashLabel}
                      </span>
                      <span className="mt-0.5 block text-[9px] text-muted-foreground/62">
                        {datasetRagVerificationForScope?.verifiedAt
                          ? formatDate(datasetRagVerificationForScope.verifiedAt)
                          : canExplainWithDatasetContract
                            ? '保存后回读验证'
                            : '当前范围不校验'}
                      </span>
                    </span>
                  </div>
                </div>
              ) : null}
              </Panel>
            </div>
          )}

          <div className="space-y-2.5 p-2.5 lg:h-full lg:max-h-full lg:min-h-0 lg:overflow-y-auto lg:no-scrollbar">
            <Panel
              padding="none"
              className={SETTINGS_PANEL_CLASS}
            >
              <div className={SETTINGS_PANEL_HEADER_CLASS}>
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className={SETTINGS_PANEL_ICON_CLASS}>
                      <Database className="size-3" />
                    </div>
                    <div>
                      <h3 className="text-[14px] font-semibold text-foreground">
                        嵌入模型
                      </h3>
                      <p className="mt-1 text-[11px] font-medium leading-4 text-muted-foreground/84">
                        为 {scopeLabel} 选择入库向量模型
                      </p>
                    </div>
                  </div>
                  <span className="shrink-0 whitespace-nowrap rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-[10px] font-semibold text-primary dark:border-border/70 dark:bg-background/62">
                    {isDatasetScoped
                      ? hasDatasetEmbeddingOverride
                        ? '数据集独立配置'
                        : '继承后可覆盖'
                      : '系统默认'}
                  </span>
                </div>
              </div>

              <div className="p-3">
                {hasCustomEmbeddingModel ? (
                  <div className="mb-2 flex min-w-0 items-center gap-2 border-b border-border/45 pb-2 text-[10px]">
                    <span className="shrink-0 font-medium text-muted-foreground/72">
                      当前自定义模型
                    </span>
                    <span className="truncate font-mono font-semibold text-foreground">
                      {configuredEmbeddingModel}
                    </span>
                    <span className="shrink-0 text-muted-foreground/55">·</span>
                    <span className="shrink-0 text-muted-foreground/72">
                      {inferEmbeddingBrand(draftConfig?.embedding)}
                    </span>
                  </div>
                ) : null}
                <div className="grid gap-2 md:grid-cols-2">
                  {EMBEDDING_PRESETS.map((preset) => {
                    const model = preset.model
                    const selected = draftConfig?.embedding.model === model
                    return (
                      <button
                        key={model}
                        type="button"
                        aria-pressed={selected}
                        onClick={() =>
                          setDraftConfig((prev) =>
                            prev
                              ? {
                                  ...prev,
                                  embedding: {
                                    ...prev.embedding,
                                    provider: preset.provider,
                                    api_base: preset.apiBase,
                                    model,
                                  },
                                }
                              : null
                          )
                        }
                        className={cn(
                          'rounded-xl border p-3 text-left transition-colors duration-200',
                          selected
                            ? 'border-primary/45 bg-primary/[0.045]'
                            : 'border-border/55 bg-background hover:border-primary/30 hover:bg-muted/15 dark:border-border/70 dark:bg-background'
                        )}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex min-w-0 items-center gap-2.5">
                            <span
                              className={cn(
                                'size-3.5 shrink-0 rounded-full border',
                                selected
                                  ? 'border-primary bg-background'
                                  : 'border-border/70 bg-background'
                              )}
                            >
                              {selected ? (
                                <span className="m-[3px] block size-1.5 rounded-full bg-primary" />
                              ) : null}
                            </span>
                            <div
                              className={cn(
                                'truncate text-[12px] font-semibold',
                                selected ? 'text-primary' : 'text-foreground'
                              )}
                            >
                              {model}
                            </div>
                          </div>
                          {selected ? (
                            <span className="shrink-0 text-[9px] font-semibold text-primary">
                              已选择
                            </span>
                          ) : model === 'text-embedding-v4' ? (
                            <span className="shrink-0 text-[9px] font-semibold text-success">
                              推荐
                            </span>
                          ) : null}
                        </div>

                        <p className="mt-2 min-h-8 text-[11px] font-medium leading-4 text-muted-foreground/82">
                          {EMBEDDING_MODEL_META[model].description}
                        </p>

                        <div className="mt-2 flex min-w-0 items-center gap-1.5 border-t border-border/45 pt-2 text-[9px] text-muted-foreground/72">
                          <span className="shrink-0 font-semibold text-foreground/78">
                            {preset.brand}
                          </span>
                          <span aria-hidden="true">·</span>
                          <span className="truncate">
                            {EMBEDDING_MODEL_META[model].chips
                              .slice(1)
                              .join(' · ')}
                          </span>
                        </div>
                      </button>
                    )
                  })}
                </div>

              </div>
            </Panel>

            <Panel
              padding="none"
              className={SETTINGS_PANEL_CLASS}
            >
              <div className="border-b border-border/60 px-3 py-2.5 dark:border-border/60">
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className={SETTINGS_PANEL_ICON_CLASS}>
                      <Settings className="size-3" />
                    </div>
                    <div>
                      <h3 className="text-[14px] font-semibold text-foreground">
                        检索策略
                      </h3>
                      <p className="mt-1 text-[11px] font-medium leading-4 text-muted-foreground/84">
                        调整召回数量、阈值和检索方式
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-7 rounded-lg px-2.5 text-[10px] font-medium text-primary hover:bg-primary/[0.06] hover:text-primary"
                      onClick={handleApplyRecommendedConfig}
                    >
                      应用建议值
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-7 rounded-lg border-border/60 bg-background px-2.5 text-[10px] font-medium hover:bg-muted/20 dark:border-border/70 dark:bg-background"
                      onClick={handleResetDraft}
                      disabled={!isDirty}
                    >
                      恢复已保存
                    </Button>
                  </div>
                </div>
              </div>

              <div className="grid gap-2 p-3 xl:grid-cols-2">
                <div className="rounded-xl border border-border/55 bg-muted/[0.08] p-3 dark:border-border/70 dark:bg-muted/[0.06]">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-[11px] font-medium text-foreground">
                      召回数量（Top K）
                    </div>
                    <div className="rounded-lg border border-primary/20 bg-primary/[0.06] px-2 py-0.5 font-mono text-[13px] font-semibold text-primary">
                      {retrievalTopK}
                    </div>
                  </div>
                  <div className="mt-2.5">
                    <div className="relative h-5">
                      <div className="pointer-events-none absolute inset-x-0 top-1/2 h-1 rounded-full bg-muted/70 -translate-y-1/2 dark:bg-muted-foreground/20" />
                      <div
                        className="pointer-events-none absolute left-0 top-1/2 h-1 rounded-full bg-info/80 -translate-y-1/2 dark:bg-info"
                        style={{ width: `${topKTrackPercent}%` }}
                      />
                      <input
                        type="range"
                        min="1"
                        max="50"
                        value={retrievalTopK}
                        onChange={(e) =>
                          setDraftConfig((prev) =>
                            prev
                              ? {
                                  ...prev,
                                  rag: {
                                    ...prev.rag,
                                    retrieval_top_k: Number(e.target.value),
                                  },
                                }
                              : null
                          )
                        }
                        className="relative z-10 h-5 w-full cursor-pointer appearance-none bg-transparent [&::-webkit-slider-runnable-track]:h-5 [&::-webkit-slider-runnable-track]:bg-transparent [&::-webkit-slider-thumb]:mt-0 [&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-primary/45 [&::-webkit-slider-thumb]:bg-card [&::-webkit-slider-thumb]:shadow-[0_6px_14px_-8px_hsl(var(--primary)/0.45)] dark:[&::-webkit-slider-thumb]:border-border dark:[&::-webkit-slider-thumb]:bg-card [&::-moz-range-track]:h-5 [&::-moz-range-track]:bg-transparent [&::-moz-range-progress]:h-5 [&::-moz-range-progress]:bg-transparent [&::-moz-range-thumb]:size-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-primary/45 [&::-moz-range-thumb]:bg-card"
                      />
                    </div>
                    <div className="mt-2 flex items-center justify-between text-[10px] font-medium text-muted-foreground/78">
                      <span>1</span>
                      <span>5</span>
                      <span>10</span>
                      <span>20</span>
                      <span>50</span>
                    </div>
                    <div className="mt-1.5 text-[9px] font-medium text-muted-foreground/72">
                      建议 8～20
                    </div>
                  </div>
                </div>

                <div className="rounded-xl border border-border/55 bg-muted/[0.08] p-3 dark:border-border/70 dark:bg-muted/[0.06]">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-[11px] font-medium text-foreground">
                      相似度阈值
                    </div>
                    <div className="rounded-lg border border-primary/20 bg-primary/[0.06] px-2 py-0.5 font-mono text-[13px] font-semibold text-primary">
                      {similarityThreshold.toFixed(2)}
                    </div>
                  </div>
                  <div className="mt-2.5">
                    <div className="relative h-5">
                      <div className="pointer-events-none absolute inset-x-0 top-1/2 h-1 rounded-full bg-muted/70 -translate-y-1/2 dark:bg-muted-foreground/20" />
                      <div
                        className="pointer-events-none absolute left-0 top-1/2 h-1 rounded-full bg-info/80 -translate-y-1/2 dark:bg-info"
                        style={{ width: `${similarityTrackPercent}%` }}
                      />
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        value={similarityThreshold}
                        onChange={(e) =>
                          setDraftConfig((prev) =>
                            prev
                              ? {
                                  ...prev,
                                  rag: {
                                    ...prev.rag,
                                    similarity_threshold: Number(
                                      e.target.value
                                    ),
                                  },
                                }
                              : null
                          )
                        }
                        className="relative z-10 h-5 w-full cursor-pointer appearance-none bg-transparent [&::-webkit-slider-runnable-track]:h-5 [&::-webkit-slider-runnable-track]:bg-transparent [&::-webkit-slider-thumb]:mt-0 [&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-primary/45 [&::-webkit-slider-thumb]:bg-card [&::-webkit-slider-thumb]:shadow-[0_6px_14px_-8px_hsl(var(--primary)/0.45)] dark:[&::-webkit-slider-thumb]:border-border dark:[&::-webkit-slider-thumb]:bg-card [&::-moz-range-track]:h-5 [&::-moz-range-track]:bg-transparent [&::-moz-range-progress]:h-5 [&::-moz-range-progress]:bg-transparent [&::-moz-range-thumb]:size-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-primary/45 [&::-moz-range-thumb]:bg-card"
                      />
                    </div>
                    <div className="mt-2 flex items-center justify-between text-[10px] font-medium text-muted-foreground/78">
                      <span>0</span>
                      <span>0.25</span>
                      <span>0.50</span>
                      <span>0.75</span>
                      <span>1</span>
                    </div>
                    <div className="mt-1.5 text-[9px] font-medium text-muted-foreground/72">
                      建议 0.50～0.80
                    </div>
                  </div>
                </div>

                <div className="rounded-xl border border-border/55 bg-muted/[0.08] p-3 dark:border-border/70 dark:bg-muted/[0.06] xl:col-span-2">
                  <div className="grid gap-3 xl:grid-cols-[minmax(0,0.65fr)_minmax(280px,1.35fr)] xl:items-center">
                    <div>
                      <div className="text-[11px] font-medium text-foreground">
                        检索方式
                      </div>
                      <div className="mt-1 text-[9px] font-medium leading-4 text-muted-foreground/72">
                        {isDatasetScoped
                          ? '保存为当前数据集的检索默认值。'
                          : '选择数据集后可设置检索契约。'}
                      </div>
                    </div>
                    <Select
                      value={retrievalModeValue}
                      onValueChange={(value) =>
                        setDraftConfig((prev) =>
                          prev
                            ? {
                                ...prev,
                                rag: {
                                  ...prev.rag,
                                  retrieval_mode: value,
                                },
                              }
                            : null
                        )
                      }
                      disabled={!isDatasetScoped}
                    >
                      <SelectTrigger className="h-8 rounded-[12px] border-border/60 bg-background/74 text-[10px] font-medium dark:border-border/70 dark:bg-background/62">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="hybrid">混合检索</SelectItem>
                        <SelectItem value="vector">向量检索</SelectItem>
                        <SelectItem value="keyword">关键词检索</SelectItem>
                        <SelectItem value="mmr">MMR</SelectItem>
                        <SelectItem value="auto">Auto</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>
            </Panel>

            <Panel
              padding="none"
              className={SETTINGS_PANEL_CLASS}
            >
              <div className="grid gap-2.5 p-3 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
                <div>
                  <div className="text-[11px] font-medium text-foreground">
                    配置保存
                  </div>
                  <div className="mt-1 text-[10px] leading-4 text-muted-foreground/72">
                    {saveScopeDescription}
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-end gap-3">
                  {isDirty ? (
                    <Button
                      type="button"
                      variant="outline"
                      className="h-9 rounded-[12px] border-warning/30 bg-warning/5 px-4 text-[11px] font-medium text-warning hover:border-warning/40 hover:bg-warning/10 hover:text-warning dark:hover:bg-warning/20 dark:hover:text-warning"
                      onClick={handleResetDraft}
                    >
                      重置更改
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    variant="outline"
                    className="h-9 rounded-[12px] border-border/60 bg-background/74 px-4 text-[11px] font-medium text-muted-foreground hover:border-primary/30 hover:bg-card/82 hover:text-primary disabled:border-border/50 disabled:bg-muted/40 disabled:text-muted-foreground/60 dark:border-border/70 dark:bg-background/62 dark:disabled:border-border/70 dark:disabled:bg-background/62 dark:disabled:text-muted-foreground/55"
                    onClick={handleSaveDraft}
                    disabled={isSavingSettings || !draftConfig || !isDirty}
                  >
                    {isSavingSettings ? (
                      <Loader2 className="mr-2 size-4 animate-spin" />
                    ) : null}
                    保存配置
                  </Button>
                  <Button
                    type="button"
                    className="h-9 rounded-[12px] px-4 text-[11px] font-medium shadow-[0_16px_24px_-18px_hsl(var(--primary)/0.38)]"
                    onClick={() => {
                      onGoToRetrievalTest?.()
                    }}
                  >
                    去检索测试
                    <ChevronRight className="ml-2 size-4" />
                  </Button>
                </div>
              </div>
            </Panel>
          </div>
        </div>
      </div>

      {/* Confirm Dialog */}
      <AlertDialog
        open={confirmEmbeddingSaveOpen}
        onOpenChange={setConfirmEmbeddingSaveOpen}
      >
        <AlertDialogContent className="sm:rounded-[2rem] border-border/40 shadow-strong backdrop-blur-xl bg-background/90">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-medium">
              确认更改嵌入模型？
            </AlertDialogTitle>
            <AlertDialogDescription className="text-sm font-medium leading-relaxed">
              {embeddingChangeDescription}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="h-10 rounded-xl">
              取消
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleSave}
              className="h-10 rounded-xl bg-primary text-primary-foreground shadow-md shadow-primary/20"
            >
              确认保存配置
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

// --- KnowledgeConnectorRunsPanel 实现 ---
export function KnowledgeConnectorRunsPanel({
  selectedDatasetId,
  connectorRuns,
  connectorRunsLoading,
  onCancelConnectorRun,
  onResumeConnectorRun,
  onRetryFailedConnectorRun,
  onLoadConnectorRuns,
}: Readonly<KnowledgeConnectorRunsPanelProps>) {
  const t = useTranslations('KnowledgeSettingsPanel')
  const [runStatusFilter, setRunStatusFilter] =
    useState<ConnectorRunStatusFilter>('all')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)

  const stats = useMemo(
    () => ({
      total: connectorRuns.length,
      active: connectorRuns.filter(
        (r) => r.status === 'running' || r.status === 'pending'
      ).length,
      failed: connectorRuns.filter((r) => r.status === 'failed').length,
      completed: connectorRuns.filter((r) => r.status === 'completed').length,
    }),
    [connectorRuns]
  )

  const visibleRuns = useMemo(() => {
    let list =
      runStatusFilter === 'all'
        ? connectorRuns
        : connectorRuns.filter(
            (r) => String(r.status).toLowerCase() === runStatusFilter
          )

    return [...list].sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
  }, [connectorRuns, runStatusFilter])

  useEffect(() => {
    if (!autoRefresh || stats.active === 0) return
    const id = setInterval(
      () => onLoadConnectorRuns({ datasetId: selectedDatasetId }),
      5000
    )
    return () => clearInterval(id)
  }, [autoRefresh, stats.active, selectedDatasetId, onLoadConnectorRuns])

  return (
    <div className="flex flex-col h-full bg-background/50">
      {/* 头部：原子级操作岛 */}
      <div className="px-5 py-4 border-b border-border/40 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal className="size-3.5 text-primary/60" />
            <span className="text-[10px] font-medium uppercase tracking-[0.2em] text-foreground/80">
              {t('connectorRuns.title')}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-muted/30 border border-border/40">
              <div
                className={cn(
                  'size-1 rounded-full transition-all',
                  autoRefresh
                    ? 'bg-success animate-pulse shadow-[0_0_5px_rgba(16,185,129,0.4)]'
                    : 'bg-muted-foreground/30'
                )}
              />
              <span className="text-[9px] font-medium text-foreground/50 uppercase">
                {t('connectorRuns.liveBadge')}
              </span>
              <Switch
                checked={autoRefresh}
                onCheckedChange={setAutoRefresh}
                className="scale-[0.5] origin-right"
              />
            </div>
            <IconButton
              label="刷新"
              variant="ghost"
              className="h-6 w-6 rounded-md text-muted-foreground hover:text-foreground"
              onClick={() =>
                onLoadConnectorRuns({ datasetId: selectedDatasetId })
              }
            >
              <RefreshCw
                className={cn('size-3', connectorRunsLoading && 'animate-spin')}
              />
            </IconButton>
          </div>
        </div>

        {/* 高密度状态分段器 */}
        <div className="flex p-0.5 bg-muted/40 rounded-lg border border-border/40">
          {([
            {
              key: 'all',
              label: t('connectorRuns.summary.all'),
              count: stats.total,
              color: 'text-foreground',
            },
            {
              key: 'running',
              label: t('connectorRuns.summary.active'),
              count: stats.active,
              color: 'text-primary',
            },
            {
              key: 'failed',
              label: t('runStatus.failed'),
              count: stats.failed,
              color: 'text-destructive',
            },
            {
              key: 'completed',
              label: t('runStatus.completed'),
              count: stats.completed,
              color: 'text-success',
            },
          ] satisfies Array<{
            key: ConnectorRunStatusFilter
            label: string
            count: number
            color: string
          }>).map((item) => (
            <button
              key={item.key}
              onClick={() => setRunStatusFilter(item.key)}
              className={cn(
                'flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-[10px] font-medium transition-all duration-200',
                runStatusFilter === item.key
                  ? 'bg-background text-primary shadow-sm ring-1 ring-border/10' +
                      item.color
                  : 'text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted/40'
              )}
            >
              <span>{item.label}</span>
              <span className="tabular-nums opacity-40 text-[9px]">
                {item.count}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-2.5 no-scrollbar">
        <AnimatePresence mode="popLayout">
          {visibleRuns.length === 0 ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex flex-col items-center justify-center py-24 text-center opacity-30"
            >
              <History className="size-10 text-muted-foreground/10 mb-2" />
              <span className="text-[10px] font-medium uppercase text-muted-foreground/30">
                Quiet Environment
              </span>
            </motion.div>
          ) : (
            visibleRuns.map((run) => (
              <TaskCard
                key={run.id}
                run={run}
                t={t}
                onCancel={onCancelConnectorRun}
                onResume={onResumeConnectorRun}
                onRetry={onRetryFailedConnectorRun}
                isExpanded={expandedRunId === run.id}
                onToggleExpand={() =>
                  setExpandedRunId(expandedRunId === run.id ? null : run.id)
                }
              />
            ))
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

function TaskCard({
  run,
  t,
  onCancel,
  onResume,
  onRetry,
  isExpanded,
  onToggleExpand,
}: Readonly<TaskCardProps>) {
  const { total, processed } = getConnectorRunProgress(run.stats || {})
  const runErrors = getConnectorRunErrors(run.stats)
  const progressPct = total > 0 ? Math.round((processed / total) * 100) : 0
  const isFailed = run.status === 'failed'
  const isRunning = run.status === 'running' || run.status === 'pending'
  const isCancelled = run.status === 'cancelled'

  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className={cn(
        'group relative rounded-2xl border transition-all duration-300',
        isRunning
          ? 'border-primary/30 bg-primary/[0.03]'
          : 'border-border/40 bg-background/40 hover:border-border/80'
      )}
    >
      <div className="p-3 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <div
              className={cn(
                'size-8 shrink-0 rounded-lg flex items-center justify-center border shadow-sm',
                isFailed
                  ? 'bg-destructive/10 border-destructive/20 text-destructive'
                  : isRunning
                    ? 'bg-primary/10 border-primary/20 text-primary'
                    : 'bg-muted/40 border-border/40 text-muted-foreground'
              )}
            >
              <Link2 className="size-4" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-[12px] font-medium text-foreground truncate max-w-[140px] leading-none">
                  {run.connector_id}
                </span>
                <div
                  className={cn(
                    'size-1.5 rounded-full',
                    isFailed
                      ? 'bg-destructive shadow-[0_0_6px_rgba(var(--destructive),0.5)]'
                      : isRunning
                        ? 'bg-primary animate-pulse'
                        : 'bg-muted-foreground/30'
                  )}
                />
              </div>
              <div className="flex items-center gap-1.5 text-[9px] font-medium text-muted-foreground/40 tabular-nums mt-1 uppercase">
                <span>{formatDate(run.created_at)}</span>
                <span>·</span>
                <span>{run.id.slice(0, 8)}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            {isRunning && (
              <IconButton
                label="取消"
                variant="ghost"
                className="h-7 w-7 rounded-md text-muted-foreground hover:text-destructive"
                onClick={() => onCancel(run.id)}
              >
                <X className="size-3.5" />
              </IconButton>
            )}
            {isFailed && (
              <IconButton
                label="重试"
                variant="ghost"
                className="h-7 w-7 rounded-md text-muted-foreground hover:text-primary"
                onClick={() => onRetry(run.id)}
              >
                <RotateCcw className="size-3.5" />
              </IconButton>
            )}
            {isCancelled && onResume ? (
              <IconButton
                label="继续"
                variant="ghost"
                className="h-7 w-7 rounded-md text-muted-foreground hover:text-primary"
                onClick={() => onResume(run.id)}
              >
                <RefreshCw className="size-3.5" />
              </IconButton>
            ) : null}
            <IconButton
              label="复制"
              variant="ghost"
              className="h-7 w-7 rounded-md text-muted-foreground"
              onClick={() => {
                navigator.clipboard.writeText(run.id)
                toast.success('Copied')
              }}
            >
              <Terminal className="size-3.5" />
            </IconButton>
          </div>
        </div>

        {total > 0 && (
          <div className="space-y-1.5">
            <div className="h-1 w-full bg-muted/40 rounded-full overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${progressPct}%` }}
                className={cn(
                  'h-full transition-colors',
                  isFailed ? 'bg-destructive/60' : 'bg-primary/70'
                )}
              />
            </div>
            <div className="flex items-center justify-between px-0.5">
              <span className="text-[9px] font-medium text-foreground/40 uppercase">
                {progressPct}% Complete
              </span>
              <span className="text-[9px] font-medium text-muted-foreground/30 tabular-nums">
                {processed}/{total}
              </span>
            </div>
          </div>
        )}

        {isFailed && run.error_message && (
          <button
            onClick={onToggleExpand}
            className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-destructive/5 border border-destructive/10 text-destructive/80 hover:bg-destructive/10 transition-colors"
          >
            <span className="text-[9px] font-medium truncate uppercase">
              Error Details
            </span>
            <ChevronDown
              className={cn(
                'size-3 transition-transform',
                isExpanded && 'rotate-180'
              )}
            />
          </button>
        )}
      </div>

      <AnimatePresence>
        {isExpanded && isFailed && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden bg-foreground"
          >
            <div className="p-3 border-t border-border/5 font-mono text-[9px] leading-relaxed text-muted-foreground">
              <div className="text-rose/80 font-medium mb-1">
                ERR: {run.error_message}
              </div>
              {runErrors
                .slice(0, 2)
                .map((err) => (
	                  <div key={toTrimmedPrimitiveString(err.error ?? err.message ?? err.code, 'error')} className="mt-1 opacity-60 truncate">
	                    ! {toTrimmedPrimitiveString(err.error ?? err.message ?? err.code, 'error')}
                  </div>
                ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
