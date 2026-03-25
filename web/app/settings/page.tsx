/**
 * 设置页面 - 系统配置管理
 */
'use client'

import { useState, useEffect, useMemo } from 'react'
import { AppFrame } from '@/components/app-frame'
import { ModelProviderCard } from '@/components/model-provider-card'
import { ModelConfigDialog } from '@/components/model-config-dialog'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { MODEL_PROVIDERS } from '@/types/models'
import type { ModelProvider, ProviderConfig, ProviderCategory } from '@/types/models'
import { GovernanceSection } from './_sections/governance-section'
import { ObservabilitySection } from './_sections/observability-section'
import { RagSection } from './_sections/rag-section'
import { RuntimeControlsSection } from './_sections/runtime-controls-section'
import { UrlIngestSection } from './_sections/url-ingest-section'
import {
  type LucideIcon,
  Settings2, Database, Sliders, Lightbulb, Server, Cpu, Layers, LayoutGrid,
  ToggleLeft, ToggleRight, Save, RefreshCw, CheckCircle2, XCircle,
  Zap, FileSearch, Sparkles, Network, CloudCog, AlertCircle, Eye, EyeOff, ScanLine, FileCode, Wand2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  settingsApi,
  ltrApi,
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
  type ChatConfig,
  type LangGraphConfig,
  type CacheConfig,
  type LTRModelInfo,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { ParserDropdown } from '@/components/ui/parser-dropdown'
import { ChunkStrategyDropdown } from '@/components/ui/chunk-strategy-dropdown'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { Panel } from '@/components/ui/panel'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'

type RagSettings = NonNullable<SystemSettings['rag']>
type UrlIngestSettings = NonNullable<SystemSettings['url_ingest']>
type GovernanceSettings = NonNullable<SystemSettings['governance']>

function mergeConfig<T extends object>(current: T, patch: Partial<T>): T {
  return {
    ...current,
    ...patch,
  }
}

const CATEGORY_INFO: Record<ProviderCategory, { title: string; description: string; icon: LucideIcon }> = {
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
  metrics_log_enabled: false,
  metrics_log_include_text: false,
}

const DEFAULT_SAFETY: SafetyConfig = {
  pii_redaction_enabled: false,
  pii_redaction_mask: '[REDACTED]',
  pii_stream_holdback_chars: 128,
}

const DEFAULT_CHAT: ChatConfig = {
  stream_heartbeat_sec: 10,
  stream_cancel_on_disconnect: true,
}

const DEFAULT_LANGGRAPH: LangGraphConfig = {
  use_subgraphs: false,
}

const DEFAULT_CACHE: CacheConfig = {
  upload_dedup_enabled: false,
  chat_response_cache_enabled: false,
  chat_response_cache_ttl_sec: 300,
  chat_response_cache_max_value_bytes: 200000,
  chat_response_cache_require_empty_history: true,
}

const DEFAULT_FEATURE_FLAGS: FeatureFlags = {
  kg_enabled: false,
  deepdoc_enabled: false,
  docling_enabled: false,
  etl4llm_enabled: false,
  marker_enabled: false,
  paddle_vl_enabled: false,
  markitdown_enabled: false,
  llama_index_enabled: false,
  mineru_enabled: false,
  magicpdf_enabled: false,
}

const DEFAULT_RAG: RagSettings = {
  chunk_size: 1000,
  chunk_overlap: 200,
  chunk_min_chars: 30,
  retrieval_top_k: 5,
  similarity_threshold: 0.7,
  default_parser_backend: 'auto',
  default_chunk_strategy: 'recursive',
  bm25_index_enabled: true,
  enable_reranker: false,
}

const DEFAULT_URL_INGEST: UrlIngestSettings = {
  enabled: false,
  max_bytes: 50_000_000,
  timeout_sec: 30,
  allow_private_ips: false,
  follow_redirects: false,
}

const DEFAULT_GOVERNANCE: GovernanceSettings = {
  enabled: false,
  pii_anonymize: false,
  secrets_redact: false,
  quarantine_on_drop: false,
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

function trimmedPrimitiveString(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') return String(value).trim()
  return ''
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
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [lastUpdatedKeys, setLastUpdatedKeys] = useState<string[]>([])

  // 编辑状态
  const [editedSettings, setEditedSettings] = useState<Partial<SystemSettings>>({})

  // LTR 模型注册表（best-effort；依赖 settings 权限）
  const [ltrModels, setLtrModels] = useState<LTRModelInfo[]>([])
  const [ltrLoading, setLtrLoading] = useState(false)
  const [ltrError, setLtrError] = useState<string | null>(null)
  const [ltrMessage, setLtrMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [ltrUploading, setLtrUploading] = useState(false)
  const [ltrUploadModelFile, setLtrUploadModelFile] = useState<File | null>(null)
  const [ltrUploadManifestFile, setLtrUploadManifestFile] = useState<File | null>(null)
  const [ltrUploadResetKey, setLtrUploadResetKey] = useState(0)
  const [ltrBusyModelId, setLtrBusyModelId] = useState<string | null>(null)

  const ragMerged = useMemo(
    () => ({ ...DEFAULT_RAG, ...settings?.rag, ...editedSettings.rag }),
    [settings?.rag, editedSettings.rag]
  )
  const urlIngestMerged = useMemo(
    () => ({ ...DEFAULT_URL_INGEST, ...settings?.url_ingest, ...editedSettings.url_ingest }),
    [settings?.url_ingest, editedSettings.url_ingest]
  )
  const governanceMerged = useMemo(
    () => ({ ...DEFAULT_GOVERNANCE, ...settings?.governance, ...editedSettings.governance }),
    [settings?.governance, editedSettings.governance]
  )
  const observabilityMerged = useMemo(
    () => ({ ...DEFAULT_OBSERVABILITY, ...settings?.observability, ...editedSettings.observability }),
    [settings?.observability, editedSettings.observability]
  )
  const safetyMerged = useMemo(
    () => ({ ...DEFAULT_SAFETY, ...settings?.safety, ...editedSettings.safety }),
    [settings?.safety, editedSettings.safety]
  )
  const chatMerged = useMemo(
    () => ({ ...DEFAULT_CHAT, ...settings?.chat, ...editedSettings.chat }),
    [settings?.chat, editedSettings.chat]
  )
  const langGraphMerged = useMemo(
    () => ({ ...DEFAULT_LANGGRAPH, ...settings?.langgraph, ...editedSettings.langgraph }),
    [settings?.langgraph, editedSettings.langgraph]
  )
  const cacheMerged = useMemo(
    () => ({ ...DEFAULT_CACHE, ...settings?.cache, ...editedSettings.cache }),
    [settings?.cache, editedSettings.cache]
  )
  const isGovernanceEnabled = governanceMerged.enabled ?? false
  const isPiiAnonymizeEnabled = governanceMerged.pii_anonymize ?? false
  const isSecretsRedactEnabled = governanceMerged.secrets_redact ?? false
  const isQuarantineOnDropEnabled = governanceMerged.quarantine_on_drop ?? false

  // 加载配置
  useEffect(() => {
    loadSettings()
    loadLtrModels()
  }, [])

  const loadSettings = async () => {
    setLoading(true)
    setLoadError(null)
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
      setLoadError(formatApiError(error, '加载失败'))
    } finally {
      setLoading(false)
    }
  }

  const loadLtrModels = async () => {
    setLtrLoading(true)
    setLtrError(null)
    try {
      const res = await ltrApi.listModels()
      setLtrModels(Array.isArray(res.items) ? res.items : [])
    } catch (error) {
      setLtrError(formatApiError(error, '加载失败'))
    } finally {
      setLtrLoading(false)
    }
  }

  const formatBytes = (value: unknown): string => {
    const n = typeof value === 'number' && Number.isFinite(value) ? value : Number(value)
    if (!Number.isFinite(n) || n <= 0) return '-'
    const units = ['B', 'KB', 'MB', 'GB']
    let v = n
    let u = 0
    while (v >= 1024 && u < units.length - 1) {
      v /= 1024
      u += 1
    }
    const precision = (() => {
    if (v >= 100) {
        return 0;
    }
    else if (v >= 10) {
            return 1;
        }
        else {
            return 2;
        }
})()
    return `${v.toFixed(precision)} ${units[u]}`
  }

  const formatTime = (value: unknown): string => {
    const raw = trimmedPrimitiveString(value)
    if (!raw) return '-'
    // Best-effort render: keep stable, avoid locale/timezone surprises.
    return raw.replaceAll('T', ' ').replaceAll('Z', '').slice(0, 19)
  }

  const shortId = (value: unknown, keep: number = 8): string => {
    const s = trimmedPrimitiveString(value)
    if (!s) return '-'
    const k = Math.max(4, Math.min(32, keep))
    return s.length <= k ? s : `${s.slice(0, k)}…`
  }

  const registerLtrModel = async () => {
    if (!ltrUploadModelFile || !ltrUploadManifestFile) return
    setLtrUploading(true)
    setLtrMessage(null)
    try {
      await ltrApi.registerModel({ modelFile: ltrUploadModelFile, manifestFile: ltrUploadManifestFile })
      setLtrMessage({ type: 'success', text: '已注册 LTR 模型' })
      setLtrUploadModelFile(null)
      setLtrUploadManifestFile(null)
      setLtrUploadResetKey((k) => k + 1)
      await loadLtrModels()
    } catch (error) {
      setLtrMessage({ type: 'error', text: formatApiError(error, '注册失败') })
    } finally {
      setLtrUploading(false)
    }
  }

  const activateLtrModel = async (modelId: string) => {
    const mid = String(modelId || '').trim()
    if (!mid) return
    setLtrBusyModelId(mid)
    setLtrMessage(null)
    try {
      await ltrApi.activateModel(mid)
      setLtrMessage({ type: 'success', text: `已激活模型: ${shortId(mid, 12)}` })
      await loadLtrModels()
    } catch (error) {
      setLtrMessage({ type: 'error', text: formatApiError(error, '激活失败') })
    } finally {
      setLtrBusyModelId(null)
    }
  }

  const rollbackLtrModel = async () => {
    setLtrBusyModelId('__rollback__')
    setLtrMessage(null)
    try {
      await ltrApi.rollbackActiveModel()
      setLtrMessage({ type: 'success', text: '已回滚到上一版本' })
      await loadLtrModels()
    } catch (error) {
      setLtrMessage({ type: 'error', text: formatApiError(error, '回滚失败') })
    } finally {
      setLtrBusyModelId(null)
    }
  }

  // 保存配置
  const saveSettings = async () => {
    if (Object.keys(editedSettings).length === 0) return

    setSaving(true)
    setSaveMessage(null)
    setLastUpdatedKeys([])
    try {
      const result = await settingsApi.update(editedSettings)
      setSaveMessage({ type: 'success', text: result.message })
      setLastUpdatedKeys(result.updated_keys || [])
      await loadSettings()
      refreshCapabilities().catch(() => null)
    } catch (error) {
      setSaveMessage({ type: 'error', text: formatApiError(error, '保存失败') })
    } finally {
      setSaving(false)
      setTimeout(() => setSaveMessage(null), 5000)
    }
  }

  // 更新功能开关
  const toggleFeature = (key: keyof FeatureFlags) => {
    setEditedSettings((prev) => {
      const currentFlags = {
        ...DEFAULT_FEATURE_FLAGS,
        ...settings?.feature_flags,
        ...prev.feature_flags,
      }
      return {
        ...prev,
        feature_flags: {
          ...currentFlags,
          [key]: !currentFlags[key],
        },
      }
    })
  }

  // 获取当前功能开关状态
  const getFeatureValue = (key: keyof FeatureFlags): boolean => {
    if (editedSettings.feature_flags && key in editedSettings.feature_flags) {
      return editedSettings.feature_flags[key]
    }
    return settings?.feature_flags?.[key] ?? false
  }

  const updateObservability = (patch: Partial<ObservabilityConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      observability: mergeConfig<ObservabilityConfig>(
        {
          ...DEFAULT_OBSERVABILITY,
          ...settings?.observability,
          ...prev.observability,
        },
        patch
      ),
    }))
  }

  const updateSafety = (patch: Partial<SafetyConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      safety: mergeConfig<SafetyConfig>(
        {
          ...DEFAULT_SAFETY,
          ...settings?.safety,
          ...prev.safety,
        },
        patch
      ),
    }))
  }

  const updateLangGraph = (patch: Partial<LangGraphConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      langgraph: mergeConfig<LangGraphConfig>(
        {
          ...DEFAULT_LANGGRAPH,
          ...settings?.langgraph,
          ...prev.langgraph,
        },
        patch
      ),
    }))
  }

  const updateChat = (patch: Partial<ChatConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      chat: mergeConfig<ChatConfig>(
        {
          ...DEFAULT_CHAT,
          ...settings?.chat,
          ...prev.chat,
        },
        patch
      ),
    }))
  }

  const updateCache = (patch: Partial<CacheConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      cache: mergeConfig<CacheConfig>(
        {
          ...DEFAULT_CACHE,
          ...settings?.cache,
          ...prev.cache,
        },
        patch
      ),
    }))
  }

  const updateMagicPDF = (patch: Partial<MagicPDFConfig>) => {
    const current = (editedSettings.magicpdf || settings?.magicpdf || DEFAULT_MAGICPDF)
    const next = { ...current, ...patch }
    setEditedSettings((prev) => ({ ...prev, magicpdf: next }))
  }

  const updateEtl4Llm = (patch: Partial<Etl4LlmConfig>) => {
    const current = (editedSettings.etl4llm || settings?.etl4llm || DEFAULT_ETL4LLM)
    const next = { ...current, ...patch }
    setEditedSettings((prev) => ({ ...prev, etl4llm: next }))
  }

  const updateMarker = (patch: Partial<MarkerConfig>) => {
    const current = (editedSettings.marker || settings?.marker || DEFAULT_MARKER)
    const next = { ...current, ...patch }
    setEditedSettings((prev) => ({ ...prev, marker: next }))
  }

  const updatePaddleVL = (patch: Partial<PaddleVLConfig>) => {
    const current = (editedSettings.paddle_vl || settings?.paddle_vl || DEFAULT_PADDLE_VL)
    const next = { ...current, ...patch }
    setEditedSettings((prev) => ({ ...prev, paddle_vl: next }))
  }

  const updateRag = (patch: Partial<SystemSettings['rag']>) => {
    setEditedSettings((prev) => ({
      ...prev,
      rag: mergeConfig<RagSettings>(
        {
          ...DEFAULT_RAG,
          ...settings?.rag,
          ...prev.rag,
        },
        patch
      ),
    }))
  }

  const updateUrlIngest = (patch: Partial<SystemSettings['url_ingest']>) => {
    setEditedSettings((prev) => ({
      ...prev,
      url_ingest: mergeConfig<UrlIngestSettings>(
        {
          ...DEFAULT_URL_INGEST,
          ...settings?.url_ingest,
          ...prev.url_ingest,
        },
        patch
      ),
    }))
  }

  const updateGovernance = (patch: Partial<SystemSettings['governance']>) => {
    setEditedSettings((prev) => ({
      ...prev,
      governance: mergeConfig<GovernanceSettings>(
        {
          ...DEFAULT_GOVERNANCE,
          ...settings?.governance,
          ...prev.governance,
        },
        patch
      ),
    }))
  }

  // 检查是否有未保存的更改
  const hasChanges = Object.keys(editedSettings).length > 0

  // 当存在未保存更改时，刷新/关闭标签页给出提醒（防止误操作丢配置）。
  useEffect(() => {
    if (!hasChanges) return
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
      return ''
    }
    globalThis.window.addEventListener('beforeunload', handler)
    return () => globalThis.window.removeEventListener('beforeunload', handler)
  }, [hasChanges])

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
      } catch (error) {
        setSaveMessage({ type: 'error', text: formatApiError(error, '保存失败') })
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
    const styles: Record<string, { bg: string; border: string; text: string; iconBg: string }> = {
      primary: {
        bg: 'bg-primary/10',
        border: 'border-primary/25',
        text: 'text-primary',
        iconBg: 'bg-primary/15',
      },
      info: {
        bg: 'bg-info/10',
        border: 'border-info/25',
        text: 'text-info',
        iconBg: 'bg-info/15',
      },
      success: {
        bg: 'bg-success/10',
        border: 'border-success/25',
        text: 'text-success',
        iconBg: 'bg-success/15',
      },
      warning: {
        bg: 'bg-warning/10',
        border: 'border-warning/25',
        text: 'text-warning',
        iconBg: 'bg-warning/15',
      },
    }

    const key =
      (() => {
    if (color === 'green') {
        return 'success';
    }
    else if (color === 'orange') {
            return 'warning';
        }
        else if (color === 'cyan') {
                return 'primary';
            }
            else {
                return 'info';
            }
})()

    return styles[key] || styles.info
  }

  return (
    <AppFrame>
      <PageScaffold
        title="设置与配置"
        badge="SETTINGS"
        icon={Settings2}
        iconColor="text-primary"
        description="管理功能开关、模型接入及系统参数"
        top={
          (loadError || saveMessage) ? (
            <div className="space-y-3">
              {loadError && (
                <Alert variant="destructive" className="shadow-soft/40">
                  <XCircle className="h-4 w-4" />
                  <div>
                    <AlertTitle>加载失败</AlertTitle>
                    <AlertDescription className="text-foreground/80">
                      {loadError}
                    </AlertDescription>
                  </div>
                </Alert>
              )}
              {saveMessage && (
                <Alert
                  variant={saveMessage.type === 'success' ? 'success' : 'destructive'}
                  className="shadow-soft/40"
                >
                  {saveMessage.type === 'success' ? (
                    <CheckCircle2 className="h-4 w-4" />
                  ) : (
                    <XCircle className="h-4 w-4" />
                  )}
                  <div>
                    <AlertTitle>
                      {saveMessage.type === 'success' ? '保存成功' : '保存失败'}
                    </AlertTitle>
                    <AlertDescription className="text-foreground/80 space-y-2">
                      <div>{saveMessage.text}</div>
                      {saveMessage.type === 'success' && lastUpdatedKeys.length > 0 && (
                        <div className="text-xs text-muted-foreground">
                          Updated: {lastUpdatedKeys.slice(0, 10).join(', ')}
                          {lastUpdatedKeys.length > 10 ? ` (+${lastUpdatedKeys.length - 10})` : ''}
                        </div>
                      )}
                    </AlertDescription>
                  </div>
                </Alert>
              )}
            </div>
          ) : null
        }
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => {
                loadSettings()
                loadLtrModels()
              }}
              disabled={loading}
              className="gap-2"
            >
              <RefreshCw className={cn("w-4 h-4", loading && "animate-spin motion-reduce:animate-none")} />
              刷新
            </Button>
            <Button
              onClick={saveSettings}
              disabled={!hasChanges || saving}
              className="gap-2"
            >
              <Save className={cn("w-4 h-4", saving && "animate-pulse motion-reduce:animate-none")} />
              {saving ? "保存中..." : "保存配置"}
            </Button>
          </>
        }
      >
        {loading ? (
            <div className="flex items-center justify-center h-64">
              <RefreshCw className="w-8 h-8 animate-spin motion-reduce:animate-none text-muted-foreground" />
            </div>
          ) : (
            <div className="space-y-12">
              {/* 前端偏好设置（本地） */}
              <section>
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                    <Sliders className="h-5 w-5 text-primary" />
                    前端偏好（本地）
                  </h2>
                  <div className="flex items-center gap-2 px-3 py-1 bg-muted text-muted-foreground rounded-full text-xs font-medium border border-border">
                    <span>仅保存在浏览器，影响新上传/预览</span>
                  </div>
                </div>

                <Panel className="space-y-6" padding="lg">
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
                </Panel>
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
	                      <button
	                        type="button"
	                        key={feature.key}
	                        className={cn(
	                          "w-full text-left relative bg-card rounded-xl p-5 border-2 group focus-ring transition-colors duration-200 motion-reduce:transition-none",
	                          isEnabled ? `${colors.border} ${colors.bg}` : "border-border hover:border-border",
	                          isEdited && "ring-2 ring-blue-400 ring-offset-2"
	                        )}
	                        aria-pressed={isEnabled}
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
	                      </button>
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
                      <div className="text-sm font-medium text-foreground/80">API URL</div>
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
                      <div className="text-sm font-medium text-foreground/80">模式</div>
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
                      <div className="text-sm font-medium text-foreground/80">超时（秒）</div>
                      <Input
                        type="number"
                        min={10}
                        value={editedSettings.etl4llm?.timeout_sec ?? settings?.etl4llm?.timeout_sec ?? DEFAULT_ETL4LLM.timeout_sec}
                        onChange={(e) => updateEtl4Llm({ timeout_sec: Number.parseInt(e.target.value || '0', 10) || DEFAULT_ETL4LLM.timeout_sec })}
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
                      <div className="text-sm font-medium text-foreground/80">API URL</div>
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
                      <div className="text-sm font-medium text-foreground/80">超时（秒）</div>
                      <Input
                        type="number"
                        min={30}
                        value={editedSettings.marker?.timeout_sec ?? settings?.marker?.timeout_sec ?? DEFAULT_MARKER.timeout_sec}
                        onChange={(e) => updateMarker({ timeout_sec: Number.parseInt(e.target.value || '0', 10) || DEFAULT_MARKER.timeout_sec })}
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
                      <div className="text-sm font-medium text-foreground/80">API URL</div>
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
                      <div className="text-sm font-medium text-foreground/80">超时（秒）</div>
                      <Input
                        type="number"
                        min={30}
                        value={editedSettings.paddle_vl?.timeout_sec ?? settings?.paddle_vl?.timeout_sec ?? DEFAULT_PADDLE_VL.timeout_sec}
                        onChange={(e) => updatePaddleVL({ timeout_sec: Number.parseInt(e.target.value || '0', 10) || DEFAULT_PADDLE_VL.timeout_sec })}
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
                      <div className="text-sm font-medium text-foreground/80">解析方法</div>
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
                      <div className="text-sm font-medium text-foreground/80">语言（可选）</div>
                      <Input
                        value={editedSettings.magicpdf?.lang ?? settings?.magicpdf?.lang ?? DEFAULT_MAGICPDF.lang}
                        onChange={(e) => updateMagicPDF({ lang: e.target.value })}
                        placeholder='例如 "ch"'
                      />
                    </div>

                    <div className="space-y-2">
                      <div className="text-sm font-medium text-foreground/80">超时（秒）</div>
                      <Input
                        type="number"
                        min={30}
                        value={editedSettings.magicpdf?.timeout_sec ?? settings?.magicpdf?.timeout_sec ?? DEFAULT_MAGICPDF.timeout_sec}
                        onChange={(e) => updateMagicPDF({ timeout_sec: Number.parseInt(e.target.value || '0', 10) || DEFAULT_MAGICPDF.timeout_sec })}
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
                    <Database className="h-5 w-5 text-primary" />
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
                    <Server className="h-5 w-5 text-primary" />
                    模型服务商
                  </h2>
                  <div className="flex items-center gap-2 px-3 py-1 bg-primary/10 text-primary rounded-full text-xs font-medium border border-primary/20">
                    <Lightbulb className="h-3 w-3" />
                    <span>点击卡片配置 API Key</span>
                  </div>
                </div>

                <div className="space-y-8">
                  {(['model', 'embedding', 'reranker'] as ProviderCategory[]).map((category) => {
                    const InfoIcon = CATEGORY_INFO[category].icon
                    return (
                      <div key={category} className="bg-card rounded-2xl p-6 border border-border shadow-sm hover:shadow-md transition-shadow duration-200 motion-reduce:transition-none">
                        <div className="flex items-start gap-4 mb-6">
                          <div className="h-11 w-11 shrink-0 rounded-xl border border-border bg-muted/50 flex items-center justify-center">
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

              {/* LTR 模型注册表 */}
              <section>
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                    <Layers className="h-5 w-5 text-primary" />
                    LTR 模型注册表
                  </h2>
                  <div className="flex items-center gap-2 px-3 py-1 bg-muted text-muted-foreground rounded-full text-xs font-medium border border-border">
                    <span>支持激活与一键回滚</span>
                  </div>
                </div>

                <div className="space-y-4">
                  {ltrError ? (
                    <Alert variant="destructive" className="shadow-soft/40">
                      <XCircle className="h-4 w-4" />
                      <div>
                        <AlertTitle>LTR 注册表加载失败</AlertTitle>
                        <AlertDescription className="text-foreground/80">{ltrError}</AlertDescription>
                      </div>
                    </Alert>
                  ) : null}

                  {ltrMessage ? (
                    <Alert
                      variant={ltrMessage.type === 'success' ? 'success' : 'destructive'}
                      className="shadow-soft/40"
                    >
                      {ltrMessage.type === 'success' ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
                      <div>
                        <AlertTitle>{ltrMessage.type === 'success' ? '操作成功' : '操作失败'}</AlertTitle>
                        <AlertDescription className="text-foreground/80">{ltrMessage.text}</AlertDescription>
                      </div>
                    </Alert>
                  ) : null}

                  <Panel padding="lg" className="space-y-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="text-sm font-semibold text-foreground">上传并注册</div>
                        <div className="text-xs text-muted-foreground mt-1 text-pretty">
                          需要上传 XGBoost JSON 模型文件与 sidecar manifest（会校验 sha256 与 feature schema）。
                        </div>
                      </div>
                      <Button
                        onClick={registerLtrModel}
                        disabled={!ltrUploadModelFile || !ltrUploadManifestFile || ltrUploading}
                        className="gap-2"
                      >
                        <RefreshCw className={cn("h-4 w-4", ltrUploading && "animate-spin motion-reduce:animate-none")} />
                        {ltrUploading ? '注册中...' : '注册模型'}
                      </Button>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">模型文件（JSON）</div>
                        <Input
                          key={`ltr-model-${ltrUploadResetKey}`}
                          type="file"
                          accept=".json,application/json"
                          onChange={(e) => setLtrUploadModelFile(e.target.files?.[0] || null)}
                        />
                      </div>
                      <div className="space-y-2">
                        <div className="text-sm font-medium text-foreground/80">Manifest（JSON）</div>
                        <Input
                          key={`ltr-manifest-${ltrUploadResetKey}`}
                          type="file"
                          accept=".json,application/json"
                          onChange={(e) => setLtrUploadManifestFile(e.target.files?.[0] || null)}
                        />
                      </div>
                    </div>
                  </Panel>

                  <Panel padding="lg" className="space-y-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-foreground">已注册模型</div>
                        <div className="text-xs text-muted-foreground mt-1">
                          激活后会在后端运行时使用该模型进行 LTR 重排序（失败时 fail-closed）。
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button
                          variant="outline"
                          onClick={loadLtrModels}
                          disabled={ltrLoading || ltrBusyModelId !== null}
                          className="gap-2"
                        >
                          <RefreshCw className={cn("h-4 w-4", ltrLoading && "animate-spin motion-reduce:animate-none")} />
                          刷新列表
                        </Button>

                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button
                              variant="outline"
                              disabled={ltrLoading || ltrModels.length === 0 || ltrBusyModelId !== null}
                              className="gap-2"
                            >
                              <AlertCircle className="h-4 w-4" />
                              回滚
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>回滚 LTR 模型？</AlertDialogTitle>
                              <AlertDialogDescription className="text-pretty">
                                这会将当前激活模型切换回上一版本（仅支持一步回滚）。如果没有上一版本，会返回错误。
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>取消</AlertDialogCancel>
                              <AlertDialogAction
                                onClick={() => rollbackLtrModel()}
                                className="gap-2"
                              >
                                确认回滚
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </div>
                    </div>

                    {ltrModels.length === 0 ? (
                      <div className="rounded-xl border border-border bg-muted/30 p-6">
                        <div className="text-sm font-medium text-foreground">暂无已注册模型</div>
                        <div className="text-xs text-muted-foreground mt-1">
                          先在上方上传并注册一个模型，再进行激活或回滚。
                        </div>
                      </div>
                    ) : (
                      <div className="overflow-x-auto rounded-xl border border-border">
                        <table aria-label="系统设置分组配置" className="w-full text-sm">
                          <thead className="bg-muted/40">
                            <tr className="text-left">
                              <th className="px-3 py-2 font-medium text-muted-foreground">状态</th>
                              <th className="px-3 py-2 font-medium text-muted-foreground">模型 ID</th>
                              <th className="px-3 py-2 font-medium text-muted-foreground">sha256</th>
                              <th className="px-3 py-2 font-medium text-muted-foreground">特征</th>
                              <th className="px-3 py-2 font-medium text-muted-foreground tabular-nums">大小</th>
                              <th className="px-3 py-2 font-medium text-muted-foreground">创建时间</th>
                              <th className="px-3 py-2 font-medium text-muted-foreground">操作</th>
                            </tr>
                          </thead>
                          <tbody>
                            {ltrModels.map((m) => {
                              const isActive = Boolean(m.active)
                              const isBusy = ltrBusyModelId === String(m.model_id || '').trim()
                              return (
                                <tr
                                  key={m.model_id}
                                  className={cn(
                                    "border-t border-border",
                                    isActive && "bg-emerald-50/50 dark:bg-emerald-500/10"
                                  )}
                                >
                                  <td className="px-3 py-2">
                                    {isActive ? (
                                      <span className="inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full border bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/30">
                                        <CheckCircle2 className="h-3 w-3" />
                                        ACTIVE
                                      </span>
                                    ) : (
                                      <span className="inline-flex items-center text-xs px-2 py-0.5 rounded-full border bg-muted text-muted-foreground border-border">
                                        idle
                                      </span>
                                    )}
                                  </td>
                                  <td className="px-3 py-2 font-mono text-xs tabular-nums">
                                    <span title={m.model_id}>{shortId(m.model_id, 16)}</span>
                                  </td>
                                  <td className="px-3 py-2 font-mono text-xs tabular-nums">
                                    <span title={m.model_sha256}>{shortId(m.model_sha256, 12)}</span>
                                  </td>
                                  <td className="px-3 py-2 text-xs text-muted-foreground">
                                    <div className="tabular-nums">v{m.feature_spec_version}</div>
                                    <div className="truncate max-w-[18rem]" title={m.feature_schema || ''}>
                                      {m.feature_schema || '-'}
                                    </div>
                                    <div className="tabular-nums">{Array.isArray(m.feature_names) ? m.feature_names.length : 0} dims</div>
                                  </td>
                                  <td className="px-3 py-2 text-xs tabular-nums">{formatBytes(m.size_bytes)}</td>
                                  <td className="px-3 py-2 text-xs tabular-nums">{formatTime(m.created_at)}</td>
                                  <td className="px-3 py-2">
                                    {isActive ? (
                                      <Button variant="outline" disabled className="h-8 px-3 text-xs">
                                        已激活
                                      </Button>
                                    ) : (
                                      <AlertDialog>
                                        <AlertDialogTrigger asChild>
                                          <Button
                                            variant="outline"
                                            disabled={ltrBusyModelId !== null}
                                            className="h-8 px-3 text-xs gap-2"
                                          >
                                            <RefreshCw className={cn("h-3.5 w-3.5", isBusy && "animate-spin motion-reduce:animate-none")} />
                                            激活
                                          </Button>
                                        </AlertDialogTrigger>
                                        <AlertDialogContent>
                                          <AlertDialogHeader>
                                            <AlertDialogTitle>激活该 LTR 模型？</AlertDialogTitle>
                                            <AlertDialogDescription className="text-pretty">
                                              将切换当前在线重排序模型到该版本。你可以使用“回滚”退回到上一版本。
                                            </AlertDialogDescription>
                                          </AlertDialogHeader>
                                          <div className="rounded-lg border border-border bg-muted/30 p-3 text-xs space-y-1">
                                            <div className="font-mono">model_id: {String(m.model_id || '')}</div>
                                            <div className="font-mono">sha256: {String(m.model_sha256 || '')}</div>
                                          </div>
                                          <AlertDialogFooter>
                                            <AlertDialogCancel>取消</AlertDialogCancel>
                                            <AlertDialogAction onClick={() => activateLtrModel(String(m.model_id || ''))}>
                                              确认激活
                                            </AlertDialogAction>
                                          </AlertDialogFooter>
                                        </AlertDialogContent>
                                      </AlertDialog>
                                    )}
                                  </td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </Panel>
                </div>
              </section>

	              <RagSection rag={ragMerged} updateRag={updateRag} />

	              <UrlIngestSection
	                urlIngest={urlIngestMerged}
	                updateUrlIngest={updateUrlIngest}
	              />

	              <GovernanceSection
	                isGovernanceEnabled={isGovernanceEnabled}
	                isPiiAnonymizeEnabled={isPiiAnonymizeEnabled}
	                isSecretsRedactEnabled={isSecretsRedactEnabled}
	                isQuarantineOnDropEnabled={isQuarantineOnDropEnabled}
	                updateGovernance={updateGovernance}
	              />

	              <ObservabilitySection
	                observability={observabilityMerged}
	                defaults={DEFAULT_OBSERVABILITY}
	                updateObservability={updateObservability}
	              />

	              <RuntimeControlsSection
	                chat={chatMerged}
	                chatDefaults={DEFAULT_CHAT}
	                updateChat={updateChat}
	                cache={cacheMerged}
	                cacheDefaults={DEFAULT_CACHE}
	                updateCache={updateCache}
	                safety={safetyMerged}
	                safetyDefaults={DEFAULT_SAFETY}
	                updateSafety={updateSafety}
	                langgraph={langGraphMerged}
	                langGraphDefaults={DEFAULT_LANGGRAPH}
	                updateLangGraph={updateLangGraph}
	              />
            </div>
          )}
      </PageScaffold>

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
function StatusCard({ label, connected, message }: Readonly<{ label: string; connected: boolean; message: string }>) {
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
