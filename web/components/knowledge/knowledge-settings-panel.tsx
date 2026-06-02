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
  settingsApi,
  type SystemSettings,
} from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise, formatDate } from '@/lib/utils'
import type { ConnectorRunOut, Dataset } from '@/types'

// --- 类型定义 ---
type KnowledgeSettingsConfig = Pick<SystemSettings, 'embedding' | 'rag'>
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
  'rounded-[18px] border border-border/60 bg-card/82 shadow-[0_12px_26px_-22px_hsl(var(--primary)/0.20)] backdrop-blur-xl dark:border-border/70 dark:bg-background/62'
const SETTINGS_SIDE_PANEL_CLASS =
  'rounded-[16px] border border-border/60 bg-card/80 shadow-[0_10px_20px_-18px_hsl(var(--primary)/0.18)] backdrop-blur-xl dark:border-border/70 dark:bg-background/62'
const SETTINGS_PANEL_HEADER_CLASS = 'border-b border-border/60 px-3 py-2.5 dark:border-border/60'
const SETTINGS_SIDE_HEADER_CLASS = 'border-b border-border/60 px-3 py-3 dark:border-border/60'
const SETTINGS_PANEL_ICON_CLASS =
  'relative flex size-7 items-center justify-center rounded-[12px] border border-border/60 bg-card/82 text-primary shadow-[0_12px_18px_-16px_hsl(var(--primary)/0.28)]'
const SETTINGS_SIDE_ICON_CLASS =
  'relative mt-0.5 flex size-6 items-center justify-center rounded-lg border border-border/60 bg-card/82 text-primary/80 shadow-[inset_0_1px_0_hsl(var(--card)/0.86),0_10px_20px_-18px_hsl(var(--primary)/0.22)] dark:border-border/70 dark:bg-background/70'
const SETTINGS_CONTROL_CLASS =
  'border-border/60 bg-background/74 shadow-[inset_0_1px_0_hsl(var(--card)/0.62)] hover:border-primary/25 hover:bg-card/82 dark:border-border/70 dark:bg-background/62'
const SETTINGS_INSET_CLASS =
  'border border-border/60 bg-background/74 shadow-[inset_0_1px_0_hsl(var(--card)/0.65)] dark:border-border/70 dark:bg-background/58'
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

function findEmbeddingPreset(model: string) {
  return (
    EMBEDDING_PRESETS.find((preset) => preset.model === model) ??
    EMBEDDING_PRESETS[0]
  )
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
  return {
    embedding: {
      ...settings.embedding,
      provider: datasetEmbedding?.provider || settings.embedding.provider,
      model: datasetEmbedding?.model || settings.embedding.model,
      api_base: datasetEmbedding?.api_base ?? settings.embedding.api_base,
    },
    rag: settings.rag,
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
  const [retrievalModeView, setRetrievalModeView] = useState('vector')
  const [guideExpanded, setGuideExpanded] = useState(false)
  const [currentConfigOpen, setCurrentConfigOpen] = useState(true)

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
        await datasetApi.update(selectedDatasetId, {
          embedding_defaults: buildDatasetEmbeddingDefaults(draftConfig),
        })
        await queryClient.invalidateQueries({
          queryKey: queryKeys.datasets.all,
        })
        setSavedConfig(cloneSettingsConfig(draftConfig))
        toast.success('已保存到当前数据集，既有数据集不会被全局改动影响')
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
  const scopeDatasetId = selectedDatasetId || 'global-default'
  const selectedDatasetName =
    selectedDataset?.name || selectedDatasetId || '系统默认'
  const currentEmbeddingBrand = inferEmbeddingBrand(savedConfig?.embedding)
  const scopeLabel = isDatasetScoped ? selectedDatasetName : '系统默认'
  const scopeDetail = isDatasetScoped
    ? `${selectedDatasetName} · ${selectedDatasetId}`
    : '系统默认 · 新数据集 / 未覆盖数据集'
  const hasDatasetEmbeddingOverride = Boolean(
    selectedDataset?.embedding_defaults?.model
  )
  const saveScopeDescription = isDatasetScoped
    ? '保存到当前数据集元数据；只影响该数据集后续入库和后续迁移策略。'
    : '写入系统默认配置；用于新数据集或未设置独立 embedding 的数据集。'
  const embeddingChangeDescription = isDatasetScoped
    ? '这次只更新当前数据集的 embedding 配置，不会改动其他已维护数据集。已有已解析文档不会自动重新嵌入；隔离中的文档保持隔离状态，只有人工释放或显式重新入库时才会进入向量化。'
    : '这次只更新系统默认 embedding 配置，不会自动迁移已有数据集向量。已经设置独立 embedding 的数据集不会被覆盖；隔离中的文档也不会因为默认配置变化而重新嵌入。'
  const retrievalTopK = draftConfig?.rag.retrieval_top_k ?? 5
  const similarityThreshold = draftConfig?.rag.similarity_threshold ?? 0.7
  const estimatedRecall = Math.max(
    68,
    Math.min(92, Math.round(70 + retrievalTopK * 0.8 - similarityThreshold * 8))
  )
  const baselineRecall = Math.max(60, estimatedRecall - 4)
  const noisePercent = Math.max(6, Math.round((1 - similarityThreshold) * 40))
  const baselineNoise = Math.max(4, noisePercent - 6)
  const latencyMs = Math.max(60, Math.round(70 + retrievalTopK * 5))
  const baselineLatency = Math.max(40, latencyMs - 30)
  const diversityDelta =
    retrievalTopK >= 10 ? '较高' : retrievalTopK >= 6 ? '中等' : '偏低'
  const topKTrackPercent = ((retrievalTopK - 1) / (50 - 1)) * 100
  const similarityTrackPercent = similarityThreshold * 100
  const comparisonMetrics: Record<
    EmbeddingPresetModel,
    Array<{ label: string; value: string; dots: number; tone: string }>
  > = {
    'text-embedding-v4': [
      { label: '准确率', value: '高', dots: 4, tone: 'bg-success' },
      { label: '成本', value: '中等', dots: 2, tone: 'bg-warning' },
      { label: '速度', value: '快', dots: 4, tone: 'bg-success' },
      { label: '中文能力', value: '强', dots: 4, tone: 'bg-success' },
    ],
    'text-embedding-v3': [
      { label: '准确率', value: '中高', dots: 3, tone: 'bg-success' },
      { label: '成本', value: '中等', dots: 2, tone: 'bg-warning' },
      { label: '速度', value: '快', dots: 4, tone: 'bg-success' },
      { label: '中文能力', value: '较强', dots: 3, tone: 'bg-success' },
    ],
    'text-embedding-3-small': [
      { label: '准确率', value: '中等', dots: 2, tone: 'bg-warning' },
      { label: '成本', value: '低', dots: 3, tone: 'bg-success' },
      { label: '速度', value: '很快', dots: 4, tone: 'bg-success' },
      { label: '中文能力', value: '中等', dots: 2, tone: 'bg-warning' },
    ],
    'bge-large-zh': [
      { label: '准确率', value: '高', dots: 4, tone: 'bg-success' },
      { label: '成本', value: '高', dots: 2, tone: 'bg-rose' },
      { label: '速度', value: '中等', dots: 3, tone: 'bg-warning' },
      { label: '中文能力', value: '最强', dots: 4, tone: 'bg-success' },
    ],
  }

  return (
    <div
      className="flex h-full min-h-0 flex-col overflow-hidden bg-transparent dark:bg-background/35"
      aria-label={t('header.title')}
    >
      <div className="flex-1 min-h-0 overflow-y-auto p-2 no-scrollbar xl:overflow-y-auto">
        <div
          className={cn(
            'grid min-h-0 gap-2 xl:h-full',
            settingsSidebarCollapsed
              ? 'xl:grid-cols-1'
              : 'xl:grid-cols-[206px_minmax(0,1fr)]'
          )}
        >
          {!settingsSidebarCollapsed ? (
            <div className="space-y-2 xl:sticky xl:top-0 xl:self-start">
              <Panel
                padding="none"
                className={SETTINGS_SIDE_PANEL_CLASS}
              >
                <div className={SETTINGS_SIDE_HEADER_CLASS}>
                  <div className="flex items-start gap-2.5">
                    <div className={SETTINGS_SIDE_ICON_CLASS}>
                      <span className="pointer-events-none absolute inset-0 rounded-[inherit] bg-[linear-gradient(135deg,hsl(var(--primary)/0.12),transparent_54%)] opacity-80" />
                      <Database className="size-3" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-foreground/68">
                        Navigation
                      </div>
                      <div className="mt-0.5 text-[13px] font-medium text-foreground/92">
                        配置作用域
                      </div>
                      <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground/76">
                        选择数据集后，embedding 配置只保存到该数据集。
                      </div>
                    </div>
                  </div>
                </div>
                <div className="space-y-2.5 p-3">
                  <div className="space-y-1.5">
                    <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/72">
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
                      <div className="rounded-[11px] border border-dashed border-border/60 bg-background/52 px-2.5 py-2 text-[10px] leading-4 text-muted-foreground/70 dark:border-border/70 dark:bg-background/45">
                        暂无可选数据集，可先使用系统默认配置。
                      </div>
                    ) : null}
                  </div>

                  <div className={cn('rounded-[14px] p-2.5', SETTINGS_INSET_CLASS)}>
                    <div className="text-[10px] text-muted-foreground/72">
                      作用范围
                    </div>
                    <div className="mt-1 truncate text-[11px] font-medium text-foreground">
                      {scopeLabel}
                    </div>
                    <div className="mt-1 flex min-w-0 items-center gap-1.5 text-[9px] text-muted-foreground/64">
                      <span className="shrink-0 uppercase tracking-[0.14em]">
                        ID
                      </span>
                      <span className="truncate font-mono">{scopeDatasetId}</span>
                    </div>
                  </div>

                  <div className="rounded-[13px] border border-info/15 bg-info/[0.04] px-2.5 py-2 text-[10px] leading-4 text-muted-foreground/76 dark:border-info/20 dark:bg-info/[0.06]">
                    {isDatasetScoped
                      ? '保存后只影响这个数据集的后续入库和显式重建。'
                      : '保存后作为新数据集或未设置独立配置的数据集默认值。'}
                  </div>
                </div>
              </Panel>

              <Panel
                padding="none"
                className={SETTINGS_SIDE_PANEL_CLASS}
              >
              <div className="p-3">
                <div className="flex items-center gap-2 text-[11px] font-medium text-foreground">
                  <Info className="size-3 text-primary" />
                  配置指引
                </div>
                <p className="mt-1.5 text-[10px] leading-4.5 text-muted-foreground/74">
                  选择合适的模型与参数，可显著提升检索效果与召回准确率。
                </p>
                <button
                  type="button"
                  aria-expanded={guideExpanded}
                  aria-controls={SETTINGS_GUIDE_PANEL_ID}
                  onClick={() => setGuideExpanded((expanded) => !expanded)}
                  className="mt-2 inline-flex items-center text-[10px] font-medium text-primary hover:text-primary/80"
                >
                  {guideExpanded ? '收起配置指南' : '查看配置指南'}
                  <ChevronRight
                    className={cn(
                      'ml-1 size-3 transition-transform',
                      guideExpanded && 'rotate-90'
                    )}
                  />
                </button>
                {guideExpanded ? (
                  <div
                    id={SETTINGS_GUIDE_PANEL_ID}
                    className="mt-2.5 space-y-2 rounded-[13px] border border-border/60 bg-background/74 p-2.5 text-[9px] leading-4 text-muted-foreground/76 shadow-[inset_0_1px_0_hsl(var(--card)/0.65)] dark:border-border/70 dark:bg-background/55"
                  >
                    <div>
                      <span className="font-medium text-foreground/82">
                        模型：
                      </span>
                      <span>中文知识库优先看中文/多语言模型；数据集独立配置只影响当前范围，隔离文档不会因为配置变化自动重新嵌入。</span>
                    </div>
                    <div>
                      <span className="font-medium text-foreground/82">
                        Top K：
                      </span>
                      <span>常规问答建议 8～20；值越高召回更全，但延迟和噪声会上升。</span>
                    </div>
                    <div>
                      <span className="font-medium text-foreground/82">
                        阈值：
                      </span>
                      <span>建议 0.50～0.80；低阈值保召回，高阈值保精度。</span>
                    </div>
                  </div>
                ) : null}
              </div>
              </Panel>

              <Panel
                padding="none"
                className={SETTINGS_SIDE_PANEL_CLASS}
              >
              <div className={SETTINGS_PANEL_HEADER_CLASS}>
                <div className="flex items-center justify-between gap-3">
                  <div className="text-[11px] font-medium text-foreground">
                    当前配置
                  </div>
                  <button
                    type="button"
                    aria-expanded={currentConfigOpen}
                    aria-controls="knowledge-current-config-panel"
                    onClick={() => setCurrentConfigOpen((open) => !open)}
                    className="inline-flex size-6 items-center justify-center rounded-full border border-border/60 bg-background/74 text-foreground/72 shadow-[0_5px_12px_-10px_hsl(var(--primary)/0.28)] transition-colors hover:border-primary/25 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 dark:border-border/70 dark:bg-background/62"
                  >
                    <ChevronDown
                      className={cn(
                        'size-3.5 transition-transform duration-200',
                        !currentConfigOpen && '-rotate-90'
                      )}
                    />
                  </button>
                </div>
              </div>
              {currentConfigOpen ? (
                <div
                  id="knowledge-current-config-panel"
                  className="space-y-2.5 p-3"
                >
                  <div className="grid gap-2.5">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-[10px] text-muted-foreground/72">
                        保存状态
                      </span>
                      <span
                        className={cn(
                          'text-[10px] font-medium',
                          isDirty ? 'text-amber-600' : 'text-emerald-600'
                        )}
                      >
                        {isDirty ? '有未保存更改' : '已同步'}
                      </span>
                    </div>
                    <div className="flex items-start justify-between gap-3">
                      <span className="text-[10px] text-muted-foreground/72">
                        作用范围
                      </span>
                      <span className="min-w-0 text-right">
                        <span className="block max-w-[8rem] truncate text-[10px] font-medium text-foreground">
                          {scopeLabel}
                        </span>
                        <span className="mt-0.5 block max-w-[8rem] truncate font-mono text-[9px] text-muted-foreground/62">
                          {scopeDatasetId}
                        </span>
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-[10px] text-muted-foreground/72">
                        嵌入模型
                      </span>
                      <span className="max-w-[8rem] truncate text-right">
                        <span className="block truncate text-[10px] font-medium text-foreground">
                          {savedConfig?.embedding.model || '-'}
                        </span>
                        <span className="mt-0.5 block truncate text-[9px] text-muted-foreground/62">
                          {currentEmbeddingBrand}
                        </span>
                      </span>
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    className={cn('h-8 w-full rounded-[12px] text-[10px] font-medium', SETTINGS_CONTROL_CLASS)}
                    onClick={handleSaveDraft}
                    disabled={isSavingSettings || !draftConfig || !isDirty}
                  >
                    {isSavingSettings ? (
                      <Loader2 className="mr-2 size-3.5 animate-spin" />
                    ) : null}
                    {isDatasetScoped ? '保存数据集配置' : '保存当前配置'}
                  </Button>
                </div>
              ) : null}
              </Panel>
            </div>
          ) : null}

          <div className="space-y-2.5 xl:h-full xl:max-h-full xl:min-h-0 xl:overflow-y-auto xl:pr-1 xl:no-scrollbar">
            <Panel
              padding="none"
              className={SETTINGS_PANEL_CLASS}
            >
              <div className={SETTINGS_PANEL_HEADER_CLASS}>
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className={SETTINGS_PANEL_ICON_CLASS}>
                      <span className="pointer-events-none absolute inset-0 rounded-[inherit] bg-[linear-gradient(135deg,hsl(var(--primary)/0.12),transparent_48%)] opacity-80" />
                      <Database className="size-3" />
                    </div>
                    <div>
                      <h3 className="text-[14px] font-semibold text-foreground">
                        嵌入模型配置 / Embedding
                      </h3>
                      <p className="mt-1 text-[9px] leading-4 text-muted-foreground/70">
                        配置作用域：{scopeDetail}
                        。选择合适的向量模型，将文本转换为向量表示。
                      </p>
                    </div>
                  </div>
                  <span className="rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-[9px] font-medium text-primary dark:border-border/70 dark:bg-background/62">
                    {isDatasetScoped
                      ? hasDatasetEmbeddingOverride
                        ? '数据集独立配置'
                        : '继承后可覆盖'
                      : '系统默认'}
                  </span>
                </div>
              </div>

              <div className="p-3">
                <div className="grid gap-2 xl:grid-cols-3">
                  {EMBEDDING_PRESETS.map((preset) => {
                    const model = preset.model
                    const selected = draftConfig?.embedding.model === model
                    const metrics = comparisonMetrics[model]
                    return (
                      <button
                        key={model}
                        type="button"
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
                          'relative overflow-hidden rounded-[16px] border p-3 text-left transition-all duration-300',
                          selected
                            ? 'border-primary/45 bg-[linear-gradient(180deg,hsl(var(--primary)/0.12),hsl(var(--card)/0.84))] shadow-[0_18px_38px_-28px_hsl(var(--primary)/0.28)] ring-1 ring-primary/20'
                            : 'border-border/60 bg-card/78 hover:border-primary/30 hover:bg-background/82 hover:shadow-[0_16px_30px_-28px_hsl(var(--primary)/0.18)] dark:border-border/70 dark:bg-background/58 dark:hover:bg-primary/[0.02]'
                        )}
                      >
                        <div
                          className={cn(
                            'pointer-events-none absolute inset-x-0 top-0 h-px',
                            selected ? 'bg-primary/65' : 'bg-primary/10'
                          )}
                        />
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-3">
                            <span
                              className={cn(
                                'size-4 rounded-full border',
                                selected
                                  ? 'border-primary/65 bg-card shadow-[0_0_0_4px_hsl(var(--primary)/0.12)]'
                                  : 'border-border/60 bg-background/74 dark:border-border/70 dark:bg-background/62'
                              )}
                            >
                              {selected ? (
                                <span className="m-[3px] block size-2 rounded-full bg-primary" />
                              ) : null}
                            </span>
                            <div
                              className={cn(
                                'text-[11px] font-medium',
                                selected ? 'text-primary' : 'text-foreground'
                              )}
                            >
                              {model}
                            </div>
                            {model === 'text-embedding-v4' ? (
                              <span className="rounded-full bg-success/10 px-1.5 py-0.5 text-[9px] font-medium text-success">
                                推荐
                              </span>
                            ) : null}
                          </div>
                          {selected ? (
                            <div className="size-3 rounded-full bg-primary shadow-[0_0_12px_hsl(var(--primary)/0.35)]" />
                          ) : null}
                        </div>

                        <p className="mt-2 text-[10px] leading-4.5 text-muted-foreground/74">
                          {EMBEDDING_MODEL_META[model].description}
                        </p>

                        <div className="mt-2 flex items-center justify-between gap-3 text-[9px]">
                          <span className="rounded-full border border-border/60 bg-background/74 px-2 py-0.5 font-medium text-foreground/75 dark:border-border/70 dark:bg-background/62">
                            {preset.brand}
                          </span>
                          <span className="font-mono text-muted-foreground/62">
                            {preset.provider}
                          </span>
                        </div>

                        <div className="mt-3 grid grid-cols-4 gap-1.5">
                          {metrics.map((metric) => (
                            <div key={metric.label} className="space-y-1">
                              <div className="text-[9px] text-muted-foreground/62">
                                {metric.label}
                              </div>
                              <div className="text-[9px] font-medium text-foreground">
                                {metric.value}
                              </div>
                              <div className="flex items-center gap-1">
                                {Array.from({ length: 4 }).map((_, index) => (
                                  <span
                                    key={`${metric.label}-${index}`}
                                    className={cn(
                                      'h-1 w-1 rounded-full',
                                      index < metric.dots
                                        ? metric.tone
                                        : 'bg-muted'
                                    )}
                                  />
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>

                        <div className="mt-3 flex flex-wrap gap-1">
                          {EMBEDDING_MODEL_META[model].chips.map((chip) => (
                            <span
                              key={chip}
                              className="rounded-full bg-primary/10 px-2 py-0.5 text-[9px] font-medium text-primary"
                            >
                              {chip}
                            </span>
                          ))}
                        </div>
                      </button>
                    )
                  })}
                </div>

                <div className="mt-2.5 flex items-center justify-between gap-3 rounded-[13px] border border-info/15 bg-info/[0.04] px-3 py-2">
                  <div className="flex items-center gap-3">
                    <div className="flex size-5 items-center justify-center rounded-full bg-info/10 text-info">
                      <Info className="size-2.5" />
                    </div>
                    <div className="text-[10px] text-foreground/82">
                      当前数据建议：您的数据集中中文占比较高，建议优先使用{' '}
                      <span className="font-medium text-foreground">
                        text-embedding-v4
                      </span>{' '}
                      或本地中文增强模型，以获得更好的中文语义理解效果。
                    </div>
                  </div>
                </div>
              </div>
            </Panel>

            <Panel
              padding="none"
              className="rounded-[18px] border border-border/60 bg-card/82 shadow-[0_12px_26px_-22px_hsl(var(--primary)/0.20)] backdrop-blur-xl dark:border-border/70 dark:bg-background/62"
            >
              <div className="border-b border-border/60 px-3 py-2.5 dark:border-border/60">
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="flex size-7 items-center justify-center rounded-[12px] border border-border/60 bg-card/82 text-primary shadow-[0_12px_18px_-16px_hsl(var(--primary)/0.28)]">
                      <Settings className="size-3" />
                    </div>
                    <div>
                      <h3 className="text-[14px] font-semibold text-foreground">
                        检索策略 / Retrieval Strategy
                      </h3>
                      <p className="mt-1 text-[9px] leading-4 text-muted-foreground/70">
                        控制召回的数量与相似度阈值，影响检索结果的质量与范围。
                      </p>
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    className="h-6.5 rounded-[10px] border-border/60 bg-background/74 px-3 text-[10px] font-medium hover:bg-card/82 dark:border-border/70 dark:bg-background/62"
                    onClick={handleResetDraft}
                    disabled={!isDirty}
                  >
                    恢复已保存配置
                  </Button>
                </div>
              </div>

              <div className="grid gap-2 p-3 xl:grid-cols-[1fr_1fr_0.95fr]">
                <div className="rounded-[15px] border border-border/60 bg-background/74 p-3 shadow-[inset_0_1px_0_hsl(var(--card)/0.65)] dark:border-border/70 dark:bg-background/58">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-[11px] font-medium text-foreground">
                        TOP K（结果数量）
                      </div>
                      <div className="mt-1 text-[9px] text-muted-foreground/72">
                        返回最相关的 Top K 个结果
                      </div>
                    </div>
                    <div className="rounded-[12px] border border-primary/20 bg-primary/10 px-2.5 py-1 font-mono text-[14px] font-semibold text-primary">
                      {retrievalTopK}
                    </div>
                  </div>
                  <div className="mt-3">
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
                    <div className="mt-2 flex items-center justify-between text-[9px] text-muted-foreground/62">
                      <span>1</span>
                      <span>5</span>
                      <span>10</span>
                      <span>20</span>
                      <span>50</span>
                    </div>
                    <div className="mt-2 rounded-[12px] border border-border/60 bg-background/74 px-2.5 py-1.5 text-[9px] text-muted-foreground/72 dark:border-border/70 dark:bg-background/55">
                      建议范围：8 ～ 20
                    </div>
                  </div>
                </div>

                <div className="rounded-[15px] border border-border/60 bg-background/74 p-3 shadow-[inset_0_1px_0_hsl(var(--card)/0.65)] dark:border-border/70 dark:bg-background/58">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-[11px] font-medium text-foreground">
                        相似度阈值（Similarity Threshold）
                      </div>
                      <div className="mt-1 text-[9px] text-muted-foreground/72">
                        过滤相似度低于阈值的结果
                      </div>
                    </div>
                    <div className="rounded-[12px] border border-primary/20 bg-primary/10 px-2.5 py-1 font-mono text-[14px] font-semibold text-primary">
                      {similarityThreshold.toFixed(2)}
                    </div>
                  </div>
                  <div className="mt-3">
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
                    <div className="mt-2 flex items-center justify-between text-[9px] text-muted-foreground/62">
                      <span>0</span>
                      <span>0.25</span>
                      <span>0.50</span>
                      <span>0.75</span>
                      <span>1</span>
                    </div>
                    <div className="mt-2 rounded-[12px] border border-border/60 bg-background/74 px-2.5 py-1.5 text-[9px] text-muted-foreground/72 dark:border-border/70 dark:bg-background/55">
                      建议范围：0.50 ～ 0.80
                    </div>
                  </div>
                </div>

                <div className="rounded-[15px] border border-border/60 bg-background/74 p-3 shadow-[inset_0_1px_0_hsl(var(--card)/0.65)] dark:border-border/70 dark:bg-background/58">
                  <div className="text-[11px] font-medium text-foreground">
                    召回策略（Retrieval Mode）
                  </div>
                  <div className="mt-1 text-[9px] text-muted-foreground/72">
                    平衡召回率与结果多样性
                  </div>
                  <div className="mt-3">
                    <Select
                      value={retrievalModeView}
                      onValueChange={setRetrievalModeView}
                    >
                      <SelectTrigger className="h-8 rounded-[12px] border-border/60 bg-background/74 text-[10px] font-medium dark:border-border/70 dark:bg-background/62">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="vector">向量检索（默认）</SelectItem>
                        <SelectItem value="hybrid">混合检索</SelectItem>
                        <SelectItem value="reranker">Reranker 优先</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="mt-2 rounded-[12px] border border-border/60 bg-background/74 px-2.5 py-1.5 text-[9px] text-muted-foreground/72 dark:border-border/70 dark:bg-muted/30">
                    默认策略，适合大多数场景
                  </div>
                </div>
              </div>
            </Panel>

            <div className="grid gap-2 xl:grid-cols-[1.35fr_0.85fr]">
              <Panel
                padding="none"
                className="rounded-[18px] border border-border/60 bg-card/82 shadow-[0_12px_26px_-22px_hsl(var(--primary)/0.20)] backdrop-blur-xl dark:border-border/70 dark:bg-background/62"
              >
                <div className="p-3">
                  <div className="flex items-center gap-2">
                    <div className="text-[12px] font-medium text-foreground">
                      当前配置预估效果
                    </div>
                    <div className="text-[10px] font-medium text-muted-foreground/62">
                      （仅供参考）
                    </div>
                  </div>
                  <div className="mt-2.5 grid gap-2 md:grid-cols-4">
                    <div className="rounded-[14px] border border-border/60 bg-card/82 px-2.5 py-2.5 dark:border-border/70 dark:bg-background/58">
                      <div className="text-[10px] text-muted-foreground/66">
                        召回率
                      </div>
                      <div className="mt-1 flex items-center gap-2 font-mono text-[14px] font-semibold text-foreground">
                        {baselineRecall}%{' '}
                        <span className="text-muted-foreground/48">→</span>{' '}
                        {estimatedRecall}%
                      </div>
                      <div className="mt-1 text-[9px] text-success">
                        ↑ {estimatedRecall - baselineRecall}%
                      </div>
                    </div>
                    <div className="rounded-[14px] border border-border/60 bg-card/82 px-2.5 py-2.5 dark:border-border/70 dark:bg-background/58">
                      <div className="text-[10px] text-muted-foreground/66">
                        结果多样性
                      </div>
                      <div className="mt-1 text-[12px] font-medium text-foreground">
                        {diversityDelta}
                      </div>
                      <div className="mt-1 text-[9px] text-muted-foreground/64">
                        平衡
                      </div>
                    </div>
                    <div className="rounded-[14px] border border-border/60 bg-card/82 px-2.5 py-2.5 dark:border-border/70 dark:bg-background/58">
                      <div className="text-[10px] text-muted-foreground/66">
                        噪声率
                      </div>
                      <div className="mt-1 flex items-center gap-2 font-mono text-[14px] font-semibold text-foreground">
                        {baselineNoise}%{' '}
                        <span className="text-muted-foreground/48">→</span>{' '}
                        {noisePercent}%
                      </div>
                      <div className="mt-1 text-[9px] text-rose">
                        ↑ {noisePercent - baselineNoise}%
                      </div>
                    </div>
                    <div className="rounded-[14px] border border-border/60 bg-card/82 px-2.5 py-2.5 dark:border-border/70 dark:bg-background/58">
                      <div className="text-[10px] text-muted-foreground/66">
                        预估延迟
                      </div>
                      <div className="mt-1 flex items-center gap-2 font-mono text-[14px] font-semibold text-foreground">
                        {baselineLatency} ms{' '}
                        <span className="text-muted-foreground/48">→</span>{' '}
                        {latencyMs} ms
                      </div>
                      <div className="mt-1 text-[9px] text-rose">
                        ↑ {latencyMs - baselineLatency} ms
                      </div>
                    </div>
                  </div>
                </div>
              </Panel>

              <Panel
                padding="none"
                className="rounded-[18px] border border-border/60 bg-card/82 shadow-[0_12px_26px_-22px_hsl(var(--primary)/0.20)] backdrop-blur-xl dark:border-border/70 dark:bg-background/62"
              >
                <div className="p-3">
                  <div className="text-[12px] font-medium text-foreground">
                    系统建议
                  </div>
                  <div className="mt-2.5 space-y-2 text-[10px] leading-4.5 text-muted-foreground/74">
                    <div>• TopK 偏小，建议提升至 12～15 以提高召回率。</div>
                    <div>• 相似度阈值偏高，建议降低至 0.60 左右。</div>
                    <button
                      type="button"
                      onClick={handleApplyRecommendedConfig}
                      className="inline-flex items-center text-[10px] font-medium text-info transition-colors hover:text-info dark:text-info dark:hover:text-info/80"
                    >
                      一键应用建议配置
                      <ChevronRight className="ml-1 size-3 text-info/90 dark:text-info/90" />
                    </button>
                  </div>
                </div>
              </Panel>
            </div>

            <Panel
              padding="none"
              className="rounded-[18px] border border-border/60 bg-card/82 shadow-[0_12px_26px_-22px_hsl(var(--primary)/0.20)] backdrop-blur-xl dark:border-border/70 dark:bg-background/62"
            >
              <div className="grid gap-2.5 p-3 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
                <div>
                  <div className="text-[11px] font-medium text-foreground">
                    配置保存
                  </div>
                  <div className="mt-1 text-[10px] leading-4 text-muted-foreground/72">
                    {saveScopeDescription}保存成功后会刷新当前草稿和已保存配置。
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-end gap-3">
                  {isDirty ? (
                    <Button
                      type="button"
                      variant="outline"
                      className="h-9 rounded-[12px] border-amber-200/80 bg-amber-50/70 px-4 text-[11px] font-medium text-amber-700 hover:border-amber-300 hover:bg-amber-100/75 hover:text-amber-900 dark:border-amber-400/30 dark:bg-amber-400/10 dark:text-amber-200 dark:hover:bg-amber-400/20 dark:hover:text-amber-100"
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
  onRetry,
  isExpanded,
  onToggleExpand,
}: TaskCardProps) {
  const { total, processed } = getConnectorRunProgress(run.stats || {})
  const runErrors = getConnectorRunErrors(run.stats)
  const progressPct = total > 0 ? Math.round((processed / total) * 100) : 0
  const isFailed = run.status === 'failed'
  const isRunning = run.status === 'running' || run.status === 'pending'

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
            className="overflow-hidden bg-zinc-950"
          >
            <div className="p-3 border-t border-border/5 font-mono text-[9px] leading-relaxed text-zinc-500">
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
