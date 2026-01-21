/**
 * 设置页面 - 系统配置管理
 */
'use client'

import { useState, useEffect, useMemo } from 'react'
import { AppFrame } from '@/components/app-frame'
import { ModelProviderCard } from '@/components/model-provider-card'
import { ModelConfigDialog } from '@/components/model-config-dialog'
import { PageHeader } from '@/components/ui/page-header'
import { PageBody } from '@/components/ui/page-body'
import { PageContainer } from '@/components/ui/page-container'
import { MODEL_PROVIDERS } from '@/types/models'
import type { ModelProvider, ProviderConfig, ProviderCategory } from '@/types/models'
import {
  Settings2, Database, Sliders, Lightbulb, Server, Cpu, Layers, LayoutGrid,
  ToggleLeft, ToggleRight, Save, RefreshCw, CheckCircle2, XCircle,
  Zap, FileSearch, Sparkles, Network, CloudCog, AlertCircle, Eye, EyeOff, ScanLine, FileCode, Wand2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  settingsApi,
  metaApi,
  type SystemSettings,
  type SystemStatus,
  type BackendMeta,
  type FeatureFlags,
  type Etl4LlmConfig,
  type MarkerConfig,
  type PaddleVLConfig,
  type MagicPDFConfig,
  type ObservabilityConfig,
  type SafetyConfig,
  type LangGraphConfig,
} from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { extractBackendMessage, withRequestId } from '@/lib/api-errors'
import { ParserDropdown } from '@/components/ui/parser-dropdown'
import { ChunkStrategyDropdown } from '@/components/ui/chunk-strategy-dropdown'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'

const CATEGORY_INFO: Record<ProviderCategory, { title: string; description: string; icon: any }> = {
  model: {
    title: '语言模型',
    description: '用于对话和文本生成的大语言模型',
    icon: Server,
  },
  embedding: {
    title: '向量模型',
    description: '用于文档语义理解和检索',
    icon: Cpu,
  },
  reranker: {
    title: '重排序模型',
    description: '优化检索结果的相关性排序',
    icon: Layers,
  },
}

// 功能开关配置
const FEATURE_FLAGS_CONFIG = [
  {
    key: 'kg_enabled' as keyof FeatureFlags,
    name: 'KG 知识抽取',
    description: '启用知识图谱抽取，自动抽取文档中的实体和事件',
    icon: Sparkles,
    color: 'teal',
    dependencies: ['Milvus', 'LLM'],
  },
  {
    key: 'deepdoc_enabled' as keyof FeatureFlags,
    name: 'DeepDoc 结构化解析',
    description: '启用视觉 + OCR 解析能力，适合扫描件/图文混排 PDF（自动选择时生效）',
    icon: ScanLine,
    color: 'orange',
    dependencies: [],
  },
  {
    key: 'docling_enabled' as keyof FeatureFlags,
    name: 'Docling 结构化解析',
    description: '启用 Docling 解析，对版面/表格结构抽取更友好（自动选择时生效）',
    icon: FileSearch,
    color: 'cyan',
    dependencies: [],
  },
  {
    key: 'etl4llm_enabled' as keyof FeatureFlags,
    name: 'ETL4LLM 版面解析',
    description: '启用 ETL4LLM 版面/表格/图片解析（需自建服务，自动选择时生效）',
    icon: LayoutGrid,
    color: 'green',
    dependencies: ['ETL4LLM API URL'],
  },
  {
    key: 'marker_enabled' as keyof FeatureFlags,
    name: 'Marker 启发式解析',
    description: '启用 Marker 启发式 PDF→Markdown 解析服务（可在解析器下拉中选择）',
    icon: LayoutGrid,
    color: 'green',
    dependencies: ['Marker API URL'],
  },
  {
    key: 'paddle_vl_enabled' as keyof FeatureFlags,
    name: 'PaddleOCR-VL 外部解析',
    description: '启用 PaddleOCR-VL 外部 OCR/版面解析服务（适合扫描件 PDF，可在解析器下拉中选择）',
    icon: ScanLine,
    color: 'orange',
    dependencies: ['PaddleOCR-VL API URL'],
  },
  {
    key: 'markitdown_enabled' as keyof FeatureFlags,
    name: 'MarkItDown 文档解析',
    description: '启用多格式转 Markdown（Office/表格/PDF），自动选择与解析工作台会使用',
    icon: FileCode,
    color: 'teal',
    dependencies: [],
  },
  {
    key: 'llama_index_enabled' as keyof FeatureFlags,
    name: 'LlamaIndex 分块',
    description: '启用 LlamaIndex 高级分块策略',
    icon: Network,
    color: 'orange',
    dependencies: [],
  },
  {
    key: 'mineru_enabled' as keyof FeatureFlags,
    name: 'MinerU API',
    description: '使用 MinerU 在线 API 进行文档解析',
    icon: CloudCog,
    color: 'cyan',
    dependencies: ['MinerU API Token'],
  },
  {
    key: 'magicpdf_enabled' as keyof FeatureFlags,
    name: 'MagicPDF 本地解析',
    description: '启用 magic-pdf 本地高级解析后端（可在解析器下拉中选择）',
    icon: Wand2,
    color: 'teal',
    dependencies: ['magic-pdf'],
  },
]

const DEFAULT_OBSERVABILITY: ObservabilityConfig = {
  tool_call_log_enabled: false,
  tool_call_log_include_preview: false,
  tool_call_log_max_preview_chars: 500,
  agent_log_enabled: false,
  agent_log_include_execution_path: false,
  agent_log_max_preview_chars: 500,
}

const DEFAULT_SAFETY: SafetyConfig = {
  pii_redaction_enabled: false,
  pii_redaction_mask: '[REDACTED]',
  pii_stream_holdback_chars: 128,
}

const DEFAULT_LANGGRAPH: LangGraphConfig = {
  use_subgraphs: false,
}

const DEFAULT_MAGICPDF: MagicPDFConfig = {
  cli: 'magic-pdf',
  method: 'auto',
  lang: '',
  debug: false,
  timeout_sec: 600,
  keep_artifacts: false,
}

const DEFAULT_ETL4LLM: Etl4LlmConfig = {
  api_url: '',
  timeout_sec: 120,
  mode: 'partition',
  force_ocr: false,
  enable_formula: true,
  extract_images: true,
  filter_page_header_footer: false,
}

const DEFAULT_MARKER: MarkerConfig = {
  api_url: '',
  timeout_sec: 600,
}

const DEFAULT_PADDLE_VL: PaddleVLConfig = {
  api_url: '',
  timeout_sec: 600,
}

export default function SettingsPage() {
  const [providers, setProviders] = useState<ModelProvider[]>(MODEL_PROVIDERS)
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const { refresh: refreshCapabilities } = usePipelineCapabilities()

  // 系统配置状态
  const [settings, setSettings] = useState<SystemSettings | null>(null)
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [backendMeta, setBackendMeta] = useState<BackendMeta | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // 编辑状态
  const [editedSettings, setEditedSettings] = useState<Partial<SystemSettings>>({})
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({})

  // 加载配置
  useEffect(() => {
    loadSettings()
  }, [])

  const loadSettings = async () => {
    setLoading(true)
    try {
      const [settingsData, statusData, metaData] = await Promise.all([
        settingsApi.get(),
        settingsApi.getStatus().catch(() => null),
        metaApi.get().catch(() => null),
      ])
      setSettings(settingsData)
      setStatus(statusData)
      setBackendMeta(metaData)
      setEditedSettings({})
    } catch (error) {
      console.error('Failed to load settings:', error)
    } finally {
      setLoading(false)
    }
  }

  // 保存配置
  const saveSettings = async () => {
    if (Object.keys(editedSettings).length === 0) return

    setSaving(true)
    setSaveMessage(null)
    try {
      const result = await settingsApi.update(editedSettings)
      setSaveMessage({ type: 'success', text: result.message })
      await loadSettings()
      refreshCapabilities().catch(() => null)
    } catch (error: any) {
      const data = error?.response?.data
      const requestId = error?.response?.headers?.['x-request-id'] || data?.request_id
      const msg = extractBackendMessage(data) || error?.message || '保存失败'
      setSaveMessage({ type: 'error', text: withRequestId(msg, requestId) })
    } finally {
      setSaving(false)
      setTimeout(() => setSaveMessage(null), 5000)
    }
  }

  // 更新功能开关
  const toggleFeature = (key: keyof FeatureFlags) => {
    const currentFlags = editedSettings.feature_flags || settings?.feature_flags || {} as FeatureFlags
    const newFlags = { ...currentFlags, [key]: !currentFlags[key] }
    setEditedSettings(prev => ({ ...prev, feature_flags: newFlags as FeatureFlags }))
  }

  // 获取当前功能开关状态
  const getFeatureValue = (key: keyof FeatureFlags): boolean => {
    if (editedSettings.feature_flags && key in editedSettings.feature_flags) {
      return editedSettings.feature_flags[key]
    }
    return settings?.feature_flags?.[key] ?? false
  }

  const updateObservability = (patch: Partial<ObservabilityConfig>) => {
    const current = (editedSettings.observability || settings?.observability || DEFAULT_OBSERVABILITY) as ObservabilityConfig
    const next = { ...current, ...patch }
    setEditedSettings((prev) => ({ ...prev, observability: next }))
  }

  const updateSafety = (patch: Partial<SafetyConfig>) => {
    const current = (editedSettings.safety || settings?.safety || DEFAULT_SAFETY) as SafetyConfig
    const next = { ...current, ...patch }
    setEditedSettings((prev) => ({ ...prev, safety: next }))
  }

  const updateLangGraph = (patch: Partial<LangGraphConfig>) => {
    const current = (editedSettings.langgraph || settings?.langgraph || DEFAULT_LANGGRAPH) as LangGraphConfig
    const next = { ...current, ...patch }
    setEditedSettings((prev) => ({ ...prev, langgraph: next }))
  }

  const updateMagicPDF = (patch: Partial<MagicPDFConfig>) => {
    const current = (editedSettings.magicpdf || settings?.magicpdf || DEFAULT_MAGICPDF) as MagicPDFConfig
    const next = { ...current, ...patch }
    setEditedSettings((prev) => ({ ...prev, magicpdf: next }))
  }

  const updateEtl4Llm = (patch: Partial<Etl4LlmConfig>) => {
    const current = (editedSettings.etl4llm || settings?.etl4llm || DEFAULT_ETL4LLM) as Etl4LlmConfig
    const next = { ...current, ...patch }
    setEditedSettings((prev) => ({ ...prev, etl4llm: next }))
  }

  const updateMarker = (patch: Partial<MarkerConfig>) => {
    const current = (editedSettings.marker || settings?.marker || DEFAULT_MARKER) as MarkerConfig
    const next = { ...current, ...patch }
    setEditedSettings((prev) => ({ ...prev, marker: next }))
  }

  const updatePaddleVL = (patch: Partial<PaddleVLConfig>) => {
    const current = (editedSettings.paddle_vl || settings?.paddle_vl || DEFAULT_PADDLE_VL) as PaddleVLConfig
    const next = { ...current, ...patch }
    setEditedSettings((prev) => ({ ...prev, paddle_vl: next }))
  }

  // 检查是否有未保存的更改
  const hasChanges = Object.keys(editedSettings).length > 0

  const handleConfigure = (provider: ModelProvider) => {
    setSelectedProvider(provider)
    setDialogOpen(true)
  }

  const handleSaveConfig = async (providerId: string, config: ProviderConfig) => {
    setProviders((prev) =>
      prev.map((p) =>
        p.id === providerId
          ? { ...p, isConfigured: true, config }
          : p
      )
    )

    const provider = providers.find((p) => p.id === providerId)
    if (!provider) return

    if (provider.category === 'model') {
      setSaving(true)
      setSaveMessage(null)
      try {
        const result = await settingsApi.update({
          llm: {
            api_key: config.apiKey || '',
            api_base: config.apiBase || '',
            model: config.model || '',
            temperature: config.temperature ?? 0.7,
            timeout: config.timeout ?? 60,
            max_retries: 3,
          },
        })
        setSaveMessage({ type: 'success', text: result.message })
        await loadSettings()
      } catch (error: any) {
        const data = error?.response?.data
        const requestId = error?.response?.headers?.['x-request-id'] || data?.request_id
        const msg = extractBackendMessage(data) || error?.message || '保存失败'
        setSaveMessage({ type: 'error', text: withRequestId(msg, requestId) })
      } finally {
        setSaving(false)
      }
    }
  }

  // 按分类分组
  const groupedProviders = useMemo(() => {
    const groups: Record<ProviderCategory, ModelProvider[]> = {
      model: [],
      embedding: [],
      reranker: [],
    }
    providers.forEach((p) => {
      groups[p.category].push(p)
    })
    return groups
  }, [providers])

  const getColorClasses = (color: string) => {
    const colors: Record<string, { bg: string; border: string; text: string; iconBg: string }> = {
      teal: {
        bg: 'bg-purple-50 dark:bg-purple-500/10',
        border: 'border-purple-200 dark:border-purple-500/30',
        text: 'text-purple-600 dark:text-purple-300',
        iconBg: 'bg-purple-100 dark:bg-purple-500/20',
      },
      blue: {
        bg: 'bg-blue-50 dark:bg-blue-500/10',
        border: 'border-blue-200 dark:border-blue-500/30',
        text: 'text-blue-600 dark:text-blue-300',
        iconBg: 'bg-blue-100 dark:bg-blue-500/20',
      },
      green: {
        bg: 'bg-green-50 dark:bg-green-500/10',
        border: 'border-green-200 dark:border-green-500/30',
        text: 'text-green-600 dark:text-green-300',
        iconBg: 'bg-green-100 dark:bg-green-500/20',
      },
      orange: {
        bg: 'bg-orange-50 dark:bg-orange-500/10',
        border: 'border-orange-200 dark:border-orange-500/30',
        text: 'text-orange-600 dark:text-orange-300',
        iconBg: 'bg-orange-100 dark:bg-orange-500/20',
      },
      cyan: {
        bg: 'bg-cyan-50 dark:bg-cyan-500/10',
        border: 'border-cyan-200 dark:border-cyan-500/30',
        text: 'text-cyan-600 dark:text-cyan-300',
        iconBg: 'bg-cyan-100 dark:bg-cyan-500/20',
      },
    }
    return colors[color] || colors.blue
  }

  return (
    <AppFrame>
      <PageHeader
        title="设置与配置"
        badge="SETTINGS"
        icon={Settings2}
        iconColor="text-sky-600 dark:text-sky-400"
        description="管理功能开关、模型接入及系统参数"
        className="mx-auto w-full max-w-6xl"
      >
        <>
          {saveMessage && (
            <div
              className={cn(
                "flex items-center gap-2 px-3 py-1.5 rounded-full text-sm",
                saveMessage.type === "success"
                  ? "bg-green-50 text-green-600 dark:bg-green-500/10 dark:text-green-300"
                  : "bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-300"
              )}
            >
              {saveMessage.type === "success" ? (
                <CheckCircle2 className="w-4 h-4" />
              ) : (
                <XCircle className="w-4 h-4" />
              )}
              {saveMessage.text}
            </div>
          )}
          <Button
            variant="outline"
            onClick={loadSettings}
            disabled={loading}
            className="gap-2"
          >
            <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
            刷新
          </Button>
          <Button
            onClick={saveSettings}
            disabled={!hasChanges || saving}
            className={cn(
              "gap-2",
              hasChanges ? "bg-blue-600 hover:bg-blue-700" : "bg-muted text-muted-foreground"
            )}
          >
            <Save className={cn("w-4 h-4", saving && "animate-pulse")} />
            {saving ? "保存中..." : "保存配置"}
          </Button>
        </>
      </PageHeader>

      <PageBody>
        <PageContainer>
          {loading ? (
            <div className="flex items-center justify-center h-64">
              <RefreshCw className="w-8 h-8 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="space-y-12">
              {/* 前端偏好设置（本地） */}
              <section>
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                    <Sliders className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                    前端偏好（本地）
                  </h2>
                  <div className="flex items-center gap-2 px-3 py-1 bg-muted text-muted-foreground rounded-full text-xs font-medium border border-border">
                    <span>仅保存在浏览器，影响新上传/预览</span>
                  </div>
                </div>

                <div className="bg-card rounded-xl p-6 border border-border shadow-sm space-y-6">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-foreground/80">解析方式</div>
                      <ParserDropdown value={parserBackend} onChange={setParserBackend} />
                    </div>
                    <div className="space-y-2">
                      <div className="text-sm font-medium text-foreground/80">切块策略</div>
                      <ChunkStrategyDropdown value={chunkStrategy} onChange={setChunkStrategy} />
                    </div>
                  </div>

                  <div>
                    <div className="text-sm font-medium text-foreground/80 mb-3">入库管线</div>
                    <PipelineOptionsPanel />
                  </div>
                </div>
              </section>

              {/* 功能开关区域 */}
              <section>
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                    <Zap className="h-5 w-5 text-amber-500 dark:text-amber-300" />
                    功能开关
                  </h2>
                  <div className="flex items-center gap-2 px-3 py-1 bg-amber-50 text-amber-700 rounded-full text-xs font-medium border border-amber-100 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/30">
                    <AlertCircle className="h-3 w-3" />
                    <span>更改后需重启后端生效</span>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {FEATURE_FLAGS_CONFIG.map((feature) => {
                    const Icon = feature.icon
                    const colors = getColorClasses(feature.color)
                    const isEnabled = getFeatureValue(feature.key)
                    const isEdited = editedSettings.feature_flags && feature.key in editedSettings.feature_flags

                    return (
                      <div
                        key={feature.key}
                        className={cn(
                          "relative bg-card rounded-xl p-5 border-2 transition-all duration-200 cursor-pointer group",
                          isEnabled ? `${colors.border} ${colors.bg}` : "border-border hover:border-border",
                          isEdited && "ring-2 ring-blue-400 ring-offset-2"
                        )}
                        onClick={() => toggleFeature(feature.key)}
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex items-start gap-3">
                            <div className={cn(
                              "p-2 rounded-lg transition-colors",
                              isEnabled ? colors.iconBg : "bg-muted"
                            )}>
                              <Icon className={cn("h-5 w-5", isEnabled ? colors.text : "text-muted-foreground")} />
                            </div>
                            <div>
                              <h3 className={cn(
                                "font-medium transition-colors",
                                isEnabled ? "text-foreground" : "text-muted-foreground"
                              )}>
                                {feature.name}
                              </h3>
                              <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                                {feature.description}
                              </p>
                              {feature.dependencies.length > 0 && (
                                <div className="flex flex-wrap gap-1 mt-2">
                                  {feature.dependencies.map((dep) => (
                                    <span key={dep} className="text-[10px] px-1.5 py-0.5 bg-muted text-muted-foreground rounded">
                                      需要: {dep}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                          <div className="flex-shrink-0">
                            {isEnabled ? (
                              <ToggleRight className={cn("w-8 h-8", colors.text)} />
                            ) : (
                              <ToggleLeft className="w-8 h-8 text-muted-foreground group-hover:text-muted-foreground" />
                            )}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </section>

              {/* ETL4LLM 配置 */}
              <section>
                <h2 className="text-lg font-semibold text-foreground mb-6 flex items-center gap-2">
                  <LayoutGrid className="h-5 w-5 text-emerald-700 dark:text-emerald-300" />
                  ETL4LLM 配置
                </h2>

                <div className="bg-card border border-border rounded-2xl p-6 shadow-sm space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    <div className="space-y-2 lg:col-span-2">
                      <label className="text-sm font-medium text-foreground/80">API URL</label>
                      <Input
                        value={editedSettings.etl4llm?.api_url ?? settings?.etl4llm?.api_url ?? DEFAULT_ETL4LLM.api_url}
                        onChange={(e) => updateEtl4Llm({ api_url: e.target.value })}
                        placeholder="http://localhost:10001/v1/etl4llm/predict"
                      />
                      <div className="text-xs text-muted-foreground">
                        启用后会写入 `ETL4LLM_API_URL`，并用于解析器 `etl4llm`。
                      </div>
                    </div>

                    <div className="space-y-2">
                      <label className="text-sm font-medium text-foreground/80">模式</label>
                      <select
                        value={editedSettings.etl4llm?.mode ?? settings?.etl4llm?.mode ?? DEFAULT_ETL4LLM.mode}
                        onChange={(e) => updateEtl4Llm({ mode: e.target.value })}
                        className="w-full px-3 py-2 rounded-lg border border-border bg-card text-sm"
                      >
                        <option value="partition">partition（版面/结构）</option>
                        <option value="text">text（纯文本）</option>
                      </select>
                    </div>

                    <div className="space-y-2">
                      <label className="text-sm font-medium text-foreground/80">超时（秒）</label>
                      <Input
                        type="number"
                        min={10}
                        value={editedSettings.etl4llm?.timeout_sec ?? settings?.etl4llm?.timeout_sec ?? DEFAULT_ETL4LLM.timeout_sec}
                        onChange={(e) => updateEtl4Llm({ timeout_sec: parseInt(e.target.value || '0', 10) || DEFAULT_ETL4LLM.timeout_sec })}
                      />
                    </div>
                  </div>

                  <div className="flex items-center justify-between border-t border-border pt-4">
                    <div>
                      <div className="text-sm font-medium text-foreground/80">强制 OCR</div>
                      <div className="text-xs text-muted-foreground mt-0.5">扫描件/图片型 PDF 建议开启</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => updateEtl4Llm({ force_ocr: !(editedSettings.etl4llm?.force_ocr ?? settings?.etl4llm?.force_ocr ?? DEFAULT_ETL4LLM.force_ocr) })}
                      className={cn(
                        'px-3 py-1.5 rounded-full text-xs font-medium border',
                        (editedSettings.etl4llm?.force_ocr ?? settings?.etl4llm?.force_ocr ?? DEFAULT_ETL4LLM.force_ocr)
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30'
                          : 'bg-muted text-muted-foreground border-border'
                      )}
                    >
                      {(editedSettings.etl4llm?.force_ocr ?? settings?.etl4llm?.force_ocr ?? DEFAULT_ETL4LLM.force_ocr) ? '已开启' : '已关闭'}
                    </button>
                  </div>

                  <div className="flex items-center justify-between border-t border-border pt-4">
                    <div>
                      <div className="text-sm font-medium text-foreground/80">提取图片</div>
                      <div className="text-xs text-muted-foreground mt-0.5">输出图片引用用于预览/入库</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => updateEtl4Llm({ extract_images: !(editedSettings.etl4llm?.extract_images ?? settings?.etl4llm?.extract_images ?? DEFAULT_ETL4LLM.extract_images) })}
                      className={cn(
                        'px-3 py-1.5 rounded-full text-xs font-medium border',
                        (editedSettings.etl4llm?.extract_images ?? settings?.etl4llm?.extract_images ?? DEFAULT_ETL4LLM.extract_images)
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30'
                          : 'bg-muted text-muted-foreground border-border'
                      )}
                    >
                      {(editedSettings.etl4llm?.extract_images ?? settings?.etl4llm?.extract_images ?? DEFAULT_ETL4LLM.extract_images) ? '已开启' : '已关闭'}
                    </button>
                  </div>

                  <div className="flex items-center justify-between border-t border-border pt-4">
                    <div>
                      <div className="text-sm font-medium text-foreground/80">公式识别</div>
                      <div className="text-xs text-muted-foreground mt-0.5">尽量保留公式/LaTeX 输出</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => updateEtl4Llm({ enable_formula: !(editedSettings.etl4llm?.enable_formula ?? settings?.etl4llm?.enable_formula ?? DEFAULT_ETL4LLM.enable_formula) })}
                      className={cn(
                        'px-3 py-1.5 rounded-full text-xs font-medium border',
                        (editedSettings.etl4llm?.enable_formula ?? settings?.etl4llm?.enable_formula ?? DEFAULT_ETL4LLM.enable_formula)
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30'
                          : 'bg-muted text-muted-foreground border-border'
                      )}
                    >
                      {(editedSettings.etl4llm?.enable_formula ?? settings?.etl4llm?.enable_formula ?? DEFAULT_ETL4LLM.enable_formula) ? '已开启' : '已关闭'}
                    </button>
                  </div>

                  <div className="flex items-center justify-between border-t border-border pt-4">
                    <div>
                      <div className="text-sm font-medium text-foreground/80">过滤页眉页脚</div>
                      <div className="text-xs text-muted-foreground mt-0.5">减少检索噪音（若服务支持）</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => updateEtl4Llm({ filter_page_header_footer: !(editedSettings.etl4llm?.filter_page_header_footer ?? settings?.etl4llm?.filter_page_header_footer ?? DEFAULT_ETL4LLM.filter_page_header_footer) })}
                      className={cn(
                        'px-3 py-1.5 rounded-full text-xs font-medium border',
                        (editedSettings.etl4llm?.filter_page_header_footer ?? settings?.etl4llm?.filter_page_header_footer ?? DEFAULT_ETL4LLM.filter_page_header_footer)
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30'
                          : 'bg-muted text-muted-foreground border-border'
                      )}
                    >
                      {(editedSettings.etl4llm?.filter_page_header_footer ?? settings?.etl4llm?.filter_page_header_footer ?? DEFAULT_ETL4LLM.filter_page_header_footer) ? '已开启' : '已关闭'}
                    </button>
                  </div>
                </div>
              </section>

              {/* Marker 配置 */}
              <section>
                <h2 className="text-lg font-semibold text-foreground mb-6 flex items-center gap-2">
                  <LayoutGrid className="h-5 w-5 text-emerald-700 dark:text-emerald-300" />
                  Marker 配置
                </h2>

                <div className="bg-card border border-border rounded-2xl p-6 shadow-sm space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    <div className="space-y-2 lg:col-span-2">
                      <label className="text-sm font-medium text-foreground/80">API URL</label>
                      <Input
                        value={editedSettings.marker?.api_url ?? settings?.marker?.api_url ?? DEFAULT_MARKER.api_url}
                        onChange={(e) => updateMarker({ api_url: e.target.value })}
                        placeholder="http://localhost:2080/convert"
                      />
                      <div className="text-xs text-muted-foreground">
                        启用后会写入 `MARKER_API_URL`，并用于解析器 `marker`。
                      </div>
                    </div>

                    <div className="space-y-2">
                      <label className="text-sm font-medium text-foreground/80">超时（秒）</label>
                      <Input
                        type="number"
                        min={30}
                        value={editedSettings.marker?.timeout_sec ?? settings?.marker?.timeout_sec ?? DEFAULT_MARKER.timeout_sec}
                        onChange={(e) => updateMarker({ timeout_sec: parseInt(e.target.value || '0', 10) || DEFAULT_MARKER.timeout_sec })}
                      />
                      <div className="text-xs text-muted-foreground">
                        大文件/复杂 PDF 建议调大
                      </div>
                    </div>
                  </div>
                </div>
              </section>

              {/* PaddleOCR-VL 配置 */}
              <section>
                <h2 className="text-lg font-semibold text-foreground mb-6 flex items-center gap-2">
                  <ScanLine className="h-5 w-5 text-orange-600 dark:text-orange-300" />
                  PaddleOCR-VL 配置
                </h2>

                <div className="bg-card border border-border rounded-2xl p-6 shadow-sm space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    <div className="space-y-2 lg:col-span-2">
                      <label className="text-sm font-medium text-foreground/80">API URL</label>
                      <Input
                        value={editedSettings.paddle_vl?.api_url ?? settings?.paddle_vl?.api_url ?? DEFAULT_PADDLE_VL.api_url}
                        onChange={(e) => updatePaddleVL({ api_url: e.target.value })}
                        placeholder="http://localhost:9030/convert"
                      />
                      <div className="text-xs text-muted-foreground">
                        启用后会写入 `PADDLE_VL_API_URL`，并用于解析器 `paddle_vl`（别名：paddle-vl / paddleocr-vl）。
                      </div>
                    </div>

                    <div className="space-y-2">
                      <label className="text-sm font-medium text-foreground/80">超时（秒）</label>
                      <Input
                        type="number"
                        min={30}
                        value={editedSettings.paddle_vl?.timeout_sec ?? settings?.paddle_vl?.timeout_sec ?? DEFAULT_PADDLE_VL.timeout_sec}
                        onChange={(e) => updatePaddleVL({ timeout_sec: parseInt(e.target.value || '0', 10) || DEFAULT_PADDLE_VL.timeout_sec })}
                      />
                      <div className="text-xs text-muted-foreground">
                        扫描件/OCR 场景建议调大
                      </div>
                    </div>
                  </div>
                </div>
              </section>

              {/* MagicPDF 配置 */}
              <section>
                <h2 className="text-lg font-semibold text-foreground mb-6 flex items-center gap-2">
                  <Wand2 className="h-5 w-5 text-fuchsia-700 dark:text-fuchsia-300" />
                  MagicPDF 配置
                </h2>

                <div className="bg-card border border-border rounded-2xl p-6 shadow-sm space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-foreground/80">解析方法</label>
                      <select
                        value={editedSettings.magicpdf?.method ?? settings?.magicpdf?.method ?? DEFAULT_MAGICPDF.method}
                        onChange={(e) => updateMagicPDF({ method: e.target.value })}
                        className="w-full px-3 py-2 rounded-lg border border-border bg-card text-sm"
                      >
                        <option value="auto">auto（自动）</option>
                        <option value="txt">txt（文本优先）</option>
                        <option value="ocr">ocr（OCR 优先）</option>
                      </select>
                    </div>

                    <div className="space-y-2">
                      <label className="text-sm font-medium text-foreground/80">语言（可选）</label>
                      <Input
                        value={editedSettings.magicpdf?.lang ?? settings?.magicpdf?.lang ?? DEFAULT_MAGICPDF.lang}
                        onChange={(e) => updateMagicPDF({ lang: e.target.value })}
                        placeholder='例如 "ch"'
                      />
                    </div>

                    <div className="space-y-2">
                      <label className="text-sm font-medium text-foreground/80">超时（秒）</label>
                      <Input
                        type="number"
                        min={30}
                        value={editedSettings.magicpdf?.timeout_sec ?? settings?.magicpdf?.timeout_sec ?? DEFAULT_MAGICPDF.timeout_sec}
                        onChange={(e) => updateMagicPDF({ timeout_sec: parseInt(e.target.value || '0', 10) || DEFAULT_MAGICPDF.timeout_sec })}
                      />
                    </div>
                  </div>

                  <div className="flex items-center justify-between border-t border-border pt-4">
                    <div>
                      <div className="text-sm font-medium text-foreground/80">保留解析产物</div>
                      <div className="text-xs text-muted-foreground mt-0.5">
                        默认会在入库流程完成后清理 `.magicpdf/` 目录
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => updateMagicPDF({ keep_artifacts: !(editedSettings.magicpdf?.keep_artifacts ?? settings?.magicpdf?.keep_artifacts ?? DEFAULT_MAGICPDF.keep_artifacts) })}
                      className={cn(
                        'px-3 py-1.5 rounded-full text-xs font-medium border',
                        (editedSettings.magicpdf?.keep_artifacts ?? settings?.magicpdf?.keep_artifacts ?? DEFAULT_MAGICPDF.keep_artifacts)
                          ? 'bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200 dark:bg-fuchsia-500/10 dark:text-fuchsia-300 dark:border-fuchsia-500/30'
                          : 'bg-muted text-muted-foreground border-border'
                      )}
                    >
                      {(editedSettings.magicpdf?.keep_artifacts ?? settings?.magicpdf?.keep_artifacts ?? DEFAULT_MAGICPDF.keep_artifacts) ? '已开启' : '已关闭'}
                    </button>
                  </div>
                </div>
              </section>

              {/* 系统状态 */}
              {status && (
                <section>
                  <h2 className="text-lg font-semibold text-foreground mb-6 flex items-center gap-2">
                    <Database className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                    系统状态
                  </h2>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <StatusCard
                      label="PostgreSQL"
                      connected={status.database.connected}
                      message={status.database.message}
                    />
                    <StatusCard
                      label="Milvus"
                      connected={status.milvus.connected}
                      message={status.milvus.message}
                    />
                    <StatusCard
                      label="LLM"
                      connected={status.llm.configured}
                      message={status.llm.model}
                    />
                    <StatusCard
                      label="Embedding"
                      connected={status.embedding.configured}
                      message={status.embedding.model}
                    />
                  </div>

                  {backendMeta && (
                    <div className="mt-6 bg-card border border-border rounded-2xl p-5 shadow-sm">
                      <div className="text-sm font-medium text-foreground/80 mb-3">Backend</div>
                      <div className="text-xs text-muted-foreground space-y-2">
                        <div>
                          API: {backendMeta.name} ({backendMeta.api_version})
                          {backendMeta.build?.sha ? ` @ ${backendMeta.build.sha.slice(0, 7)}` : ''}
                        </div>
                        {backendMeta.features && (
                          <div className="flex flex-wrap gap-2">
                            <span className="px-2 py-0.5 rounded-full border border-border bg-muted">
                              auth={backendMeta.features.auth_mode || '-'}
                            </span>
                            <span className="px-2 py-0.5 rounded-full border border-border bg-muted">
                              vector={backendMeta.features.vector_backend || '-'}
                            </span>
                            {typeof backendMeta.features.task_queue_enabled === 'boolean' && (
                              <span className="px-2 py-0.5 rounded-full border border-border bg-muted">
                                queue={backendMeta.features.task_queue_enabled ? 'on' : 'off'}
                              </span>
                            )}
                          </div>
                        )}
                        {backendMeta.runtime?.python && <div>Runtime: Python {backendMeta.runtime.python}</div>}
                      </div>
                    </div>
                  )}

                  {status.parsers && (
                    <div className="mt-6 bg-card border border-border rounded-2xl p-5 shadow-sm">
                      <div className="text-sm font-medium text-foreground/80 mb-3">解析器状态</div>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(status.parsers).map(([key, info]) => (
                          <span
                            key={key}
                            title={info.message}
                            className={cn(
                              'text-xs px-2.5 py-1 rounded-full border',
                              info.available
                                ? 'bg-green-50 text-green-700 border-green-200 dark:bg-green-500/10 dark:text-green-300 dark:border-green-500/30'
                                : 'bg-muted text-muted-foreground border-border'
                            )}
                          >
                            {key} {info.available ? '可用' : '不可用'}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </section>
              )}

              {/* 模型配置区域 */}
              <section>
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                    <Server className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                    模型服务商
                  </h2>
                  <div className="flex items-center gap-2 px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-xs font-medium border border-blue-100 dark:bg-blue-500/10 dark:text-blue-300 dark:border-blue-500/30">
                    <Lightbulb className="h-3 w-3" />
                    <span>点击卡片配置 API Key</span>
                  </div>
                </div>

                <div className="space-y-8">
                  {(['model', 'embedding', 'reranker'] as ProviderCategory[]).map((category) => {
                    const InfoIcon = CATEGORY_INFO[category].icon
                    return (
                      <div key={category} className="bg-card rounded-2xl p-6 border border-border shadow-sm hover:shadow-md transition-shadow duration-300">
                        <div className="flex items-start gap-4 mb-6">
                          <div className="p-2 bg-muted rounded-lg">
                            <InfoIcon className="h-5 w-5 text-muted-foreground" />
                          </div>
                          <div>
                            <h3 className="text-base font-medium text-foreground">
                              {CATEGORY_INFO[category].title}
                            </h3>
                            <p className="text-sm text-muted-foreground mt-0.5">
                              {CATEGORY_INFO[category].description}
                            </p>
                          </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                          {groupedProviders[category].map((provider) => (
                            <ModelProviderCard
                              key={provider.id}
                              provider={provider}
                              onConfigure={handleConfigure}
                            />
                          ))}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </section>

              {/* RAG 参数设置 */}
              <section>
                <h2 className="text-lg font-semibold text-foreground mb-6 flex items-center gap-2">
                    <Sliders className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                  RAG 参数
                </h2>

                <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    <div>
                      <div className="flex justify-between items-center mb-2">
                        <label className="text-sm font-medium text-foreground/80">Top K</label>
                        <span className="text-xs bg-muted px-2 py-0.5 rounded text-muted-foreground">
                          {settings?.rag.retrieval_top_k ?? 5}
                        </span>
                      </div>
                      <input
                        type="range"
                        min="1"
                        max="20"
                        value={editedSettings.rag?.retrieval_top_k ?? settings?.rag.retrieval_top_k ?? 5}
                        onChange={(e) => {
                          const rag = { ...(settings?.rag ?? {}), ...(editedSettings.rag ?? {}), retrieval_top_k: parseInt(e.target.value) }
                          setEditedSettings(prev => ({ ...prev, rag: rag as any }))
                        }}
                        className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-blue-600"
                      />
                      <p className="text-xs text-muted-foreground mt-2">
                        每次检索返回的最相关文档片段数量
                      </p>
                    </div>

                    <div>
                      <div className="flex justify-between items-center mb-2">
                        <label className="text-sm font-medium text-foreground/80">相似度阈值</label>
                        <span className="text-xs bg-muted px-2 py-0.5 rounded text-muted-foreground">
                          {(editedSettings.rag?.similarity_threshold ?? settings?.rag.similarity_threshold ?? 0.7).toFixed(1)}
                        </span>
                      </div>
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.1"
                        value={editedSettings.rag?.similarity_threshold ?? settings?.rag.similarity_threshold ?? 0.7}
                        onChange={(e) => {
                          const rag = { ...(settings?.rag ?? {}), ...(editedSettings.rag ?? {}), similarity_threshold: parseFloat(e.target.value) }
                          setEditedSettings(prev => ({ ...prev, rag: rag as any }))
                        }}
                        className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-blue-600"
                      />
                      <p className="text-xs text-muted-foreground mt-2">
                        过滤掉相关性得分低于此值的片段
                      </p>
                    </div>

                    <div>
                      <div className="flex justify-between items-center mb-2">
                        <label className="text-sm font-medium text-foreground/80">分块大小</label>
                        <span className="text-xs bg-muted px-2 py-0.5 rounded text-muted-foreground">
                          {editedSettings.rag?.chunk_size ?? settings?.rag.chunk_size ?? 1000}
                        </span>
                      </div>
                      <input
                        type="range"
                        min="200"
                        max="4000"
                        step="100"
                        value={editedSettings.rag?.chunk_size ?? settings?.rag.chunk_size ?? 1000}
                        onChange={(e) => {
                          const rag = { ...(settings?.rag ?? {}), ...(editedSettings.rag ?? {}), chunk_size: parseInt(e.target.value) }
                          setEditedSettings(prev => ({ ...prev, rag: rag as any }))
                        }}
                        className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-blue-600"
                      />
                      <p className="text-xs text-muted-foreground mt-2">
                        文档分块的目标字符数
                      </p>
                    </div>
                  </div>
                </div>
              </section>

              {/* 观测与调试 */}
              <section>
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                    <Eye className="h-5 w-5 text-sky-600 dark:text-sky-400" />
                    观测与调试
                  </h2>
                  <div className="flex items-center gap-2 px-3 py-1 bg-sky-50 text-sky-700 rounded-full text-xs font-medium border border-sky-100 dark:bg-sky-500/10 dark:text-sky-300 dark:border-sky-500/30">
                    <span>保存后通常可立即生效</span>
                  </div>
                </div>

                <div className="bg-card border border-border rounded-2xl p-6 shadow-sm space-y-8">
                  {/* Tool call logging */}
                  <div className="space-y-3">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="text-sm font-semibold text-foreground flex items-center gap-2">
                          <FileSearch className="h-4 w-4 text-muted-foreground" />
                          Tool Call 日志
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">
                          记录工具调用耗时、成功/失败与参数键名（preview 可选，建议配合 PII 脱敏）
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() =>
                          updateObservability({
                            tool_call_log_enabled: !((editedSettings.observability?.tool_call_log_enabled ?? settings?.observability?.tool_call_log_enabled) ?? DEFAULT_OBSERVABILITY.tool_call_log_enabled),
                          })
                        }
                        className="shrink-0"
                      >
                        {((editedSettings.observability?.tool_call_log_enabled ?? settings?.observability?.tool_call_log_enabled) ?? DEFAULT_OBSERVABILITY.tool_call_log_enabled) ? (
                          <ToggleRight className="w-10 h-10 text-sky-600 dark:text-sky-400" />
                        ) : (
                          <ToggleLeft className="w-10 h-10 text-muted-foreground hover:text-muted-foreground" />
                        )}
                      </button>
                    </div>

                    {((editedSettings.observability?.tool_call_log_enabled ?? settings?.observability?.tool_call_log_enabled) ?? DEFAULT_OBSERVABILITY.tool_call_log_enabled) && (
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={((editedSettings.observability?.tool_call_log_include_preview ?? settings?.observability?.tool_call_log_include_preview) ?? DEFAULT_OBSERVABILITY.tool_call_log_include_preview)}
                            onChange={(e) => updateObservability({ tool_call_log_include_preview: e.target.checked })}
                            className="h-4 w-4 accent-sky-600"
                          />
                          <span className="text-sm text-foreground/80">包含结果 preview</span>
                        </div>
                        <div>
                          <div className="text-xs text-muted-foreground mb-1">preview 最大字符数</div>
                          <Input
                            type="number"
                            min={0}
                            max={5000}
                            value={((editedSettings.observability?.tool_call_log_max_preview_chars ?? settings?.observability?.tool_call_log_max_preview_chars) ?? DEFAULT_OBSERVABILITY.tool_call_log_max_preview_chars)}
                            onChange={(e) => updateObservability({ tool_call_log_max_preview_chars: parseInt(e.target.value || '0', 10) })}
                          />
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Agent/workflow logging */}
                  <div className="space-y-3 border-t pt-6">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="text-sm font-semibold text-foreground flex items-center gap-2">
                          <Settings2 className="h-4 w-4 text-muted-foreground" />
                          Workflow 生命周期日志
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">
                          记录工作流总耗时、steps、success/fail（可选携带 execution path）
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() =>
                          updateObservability({
                            agent_log_enabled: !((editedSettings.observability?.agent_log_enabled ?? settings?.observability?.agent_log_enabled) ?? DEFAULT_OBSERVABILITY.agent_log_enabled),
                          })
                        }
                        className="shrink-0"
                      >
                        {((editedSettings.observability?.agent_log_enabled ?? settings?.observability?.agent_log_enabled) ?? DEFAULT_OBSERVABILITY.agent_log_enabled) ? (
                          <ToggleRight className="w-10 h-10 text-sky-600 dark:text-sky-400" />
                        ) : (
                          <ToggleLeft className="w-10 h-10 text-muted-foreground hover:text-muted-foreground" />
                        )}
                      </button>
                    </div>

                    {((editedSettings.observability?.agent_log_enabled ?? settings?.observability?.agent_log_enabled) ?? DEFAULT_OBSERVABILITY.agent_log_enabled) && (
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={((editedSettings.observability?.agent_log_include_execution_path ?? settings?.observability?.agent_log_include_execution_path) ?? DEFAULT_OBSERVABILITY.agent_log_include_execution_path)}
                            onChange={(e) => updateObservability({ agent_log_include_execution_path: e.target.checked })}
                            className="h-4 w-4 accent-sky-600"
                          />
                          <span className="text-sm text-foreground/80">包含 execution path</span>
                        </div>
                        <div>
                          <div className="text-xs text-muted-foreground mb-1">错误 preview 最大字符数</div>
                          <Input
                            type="number"
                            min={0}
                            max={5000}
                            value={((editedSettings.observability?.agent_log_max_preview_chars ?? settings?.observability?.agent_log_max_preview_chars) ?? DEFAULT_OBSERVABILITY.agent_log_max_preview_chars)}
                            onChange={(e) => updateObservability({ agent_log_max_preview_chars: parseInt(e.target.value || '0', 10) })}
                          />
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Safety / PII */}
                  <div className="space-y-3 border-t pt-6">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="text-sm font-semibold text-foreground flex items-center gap-2">
                          <EyeOff className="h-4 w-4 text-muted-foreground" />
                          PII 脱敏
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">
                          对模型输入/输出与工具调用做脱敏（流式输出会做 holdback 以减少漏出）
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() =>
                          updateSafety({
                            pii_redaction_enabled: !((editedSettings.safety?.pii_redaction_enabled ?? settings?.safety?.pii_redaction_enabled) ?? DEFAULT_SAFETY.pii_redaction_enabled),
                          })
                        }
                        className="shrink-0"
                      >
                        {((editedSettings.safety?.pii_redaction_enabled ?? settings?.safety?.pii_redaction_enabled) ?? DEFAULT_SAFETY.pii_redaction_enabled) ? (
                          <ToggleRight className="w-10 h-10 text-sky-600 dark:text-sky-400" />
                        ) : (
                          <ToggleLeft className="w-10 h-10 text-muted-foreground hover:text-muted-foreground" />
                        )}
                      </button>
                    </div>

                    {((editedSettings.safety?.pii_redaction_enabled ?? settings?.safety?.pii_redaction_enabled) ?? DEFAULT_SAFETY.pii_redaction_enabled) && (
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
                        <div>
                          <div className="text-xs text-muted-foreground mb-1">脱敏占位符</div>
                          <Input
                            value={editedSettings.safety?.pii_redaction_mask ?? settings?.safety?.pii_redaction_mask ?? DEFAULT_SAFETY.pii_redaction_mask}
                            onChange={(e) => updateSafety({ pii_redaction_mask: e.target.value })}
                          />
                        </div>
                        <div>
                          <div className="text-xs text-muted-foreground mb-1">流式 holdback 字符数</div>
                          <Input
                            type="number"
                            min={0}
                            max={2048}
                            value={editedSettings.safety?.pii_stream_holdback_chars ?? settings?.safety?.pii_stream_holdback_chars ?? DEFAULT_SAFETY.pii_stream_holdback_chars}
                            onChange={(e) => updateSafety({ pii_stream_holdback_chars: parseInt(e.target.value || '0', 10) })}
                          />
                        </div>
                      </div>
                    )}
                  </div>

                  {/* LangGraph */}
                  <div className="space-y-3 border-t pt-6">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="text-sm font-semibold text-foreground flex items-center gap-2">
                          <Network className="h-4 w-4 text-muted-foreground" />
                          LangGraph 子图组合（Subgraph）
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">
                          将 retrieve/generate 作为子图节点组合（更模块化，便于后续扩展）
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() =>
                          updateLangGraph({
                            use_subgraphs: !((editedSettings.langgraph?.use_subgraphs ?? settings?.langgraph?.use_subgraphs) ?? DEFAULT_LANGGRAPH.use_subgraphs),
                          })
                        }
                        className="shrink-0"
                      >
                        {((editedSettings.langgraph?.use_subgraphs ?? settings?.langgraph?.use_subgraphs) ?? DEFAULT_LANGGRAPH.use_subgraphs) ? (
                          <ToggleRight className="w-10 h-10 text-sky-600 dark:text-sky-400" />
                        ) : (
                          <ToggleLeft className="w-10 h-10 text-muted-foreground hover:text-muted-foreground" />
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              </section>
            </div>
          )}
        </PageContainer>
      </PageBody>

      {/* 配置对话框 */}
      <ModelConfigDialog
        provider={selectedProvider}
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSave={handleSaveConfig}
      />
    </AppFrame>
  )
}

// 状态卡片组件
function StatusCard({ label, connected, message }: { label: string; connected: boolean; message: string }) {
  return (
    <div className={cn(
      "bg-card rounded-xl p-4 border transition-colors",
      connected ? "border-green-200 dark:border-green-500/40" : "border-red-200 dark:border-red-500/40"
    )}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-foreground/80">{label}</span>
        {connected ? (
          <CheckCircle2 className="w-5 h-5 text-green-500 dark:text-green-300" />
        ) : (
          <XCircle className="w-5 h-5 text-red-500 dark:text-red-300" />
        )}
      </div>
      <p className={cn(
        "text-xs truncate",
        connected ? "text-green-600 dark:text-green-300" : "text-red-600 dark:text-red-300"
      )}>
        {message || (connected ? '已连接' : '未连接')}
      </p>
    </div>
  )
}
