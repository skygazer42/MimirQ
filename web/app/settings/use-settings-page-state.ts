'use client'

import { useEffect, useMemo, useState } from 'react'

import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { formatApiError } from '@/lib/api-errors'
import {
  ltrApi,
  metaApi,
  settingsApi,
  type BackendMeta,
  type CacheConfig,
  type ChatConfig,
  type Etl4LlmConfig,
  type FeatureFlags,
  type LangGraphConfig,
  type LTRModelInfo,
  type MagicPDFConfig,
  type MarkerConfig,
  type NavigationConfig,
  type ObservabilityConfig,
  type PaddleVLConfig,
  type SafetyConfig,
  type SystemSettings,
  type SystemStatus,
  type TextInConfig,
} from '@/lib/api'
import {
  MODEL_PROVIDERS,
  type ModelProvider,
  type ProviderCategory,
  type ProviderConfig,
} from '@/types/models'

type SaveMessage = {
  type: 'success' | 'error'
  text: string
}

type RagSettings = NonNullable<SystemSettings['rag']>
type UrlIngestSettings = NonNullable<SystemSettings['url_ingest']>
type GovernanceSettings = NonNullable<SystemSettings['governance']>

function mergeConfig<T extends object>(current: T, patch: Partial<T>): T {
  return {
    ...current,
    ...patch,
  }
}

function mergeWithDefaults<T extends object>(
  defaults: T,
  current: Partial<T> | null | undefined,
  edited: Partial<T> | null | undefined
): T {
  return {
    ...defaults,
    ...current,
    ...edited,
  }
}

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

const DEFAULT_NAVIGATION: NavigationConfig = {
  user_visible_modules: [],
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
  textin_enabled: false,
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
  reranker_provider: 'llm',
  reranker_top_n: 20,
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

const DEFAULT_TEXTIN: TextInConfig = {
  api_url: 'https://api.textin.com/ai/service/v1/pdf_to_markdown',
  app_id: '',
  secret_code: '',
  timeout_sec: 180,
  parse_mode: 'auto',
  table_flavor: 'html',
  apply_document_tree: true,
  markdown_details: true,
  get_image: 'none',
  dpi: 144,
  page_count: 0,
}

function trimmedPrimitiveString(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value).trim()
  }
  return ''
}

function formatBytes(value: unknown): string {
  const n = typeof value === 'number' && Number.isFinite(value) ? value : Number(value)
  if (!Number.isFinite(n) || n <= 0) return '-'

  const units = ['B', 'KB', 'MB', 'GB']
  let v = n
  let u = 0
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024
    u += 1
  }

  const precision = v >= 100 ? 0 : v >= 10 ? 1 : 2
  return `${v.toFixed(precision)} ${units[u]}`
}

function formatTime(value: unknown): string {
  const raw = trimmedPrimitiveString(value)
  if (!raw) return '-'
  return raw.replaceAll('T', ' ').replaceAll('Z', '').slice(0, 19)
}

function shortId(value: unknown, keep: number = 8): string {
  const s = trimmedPrimitiveString(value)
  if (!s) return '-'
  const k = Math.max(4, Math.min(32, keep))
  return s.length <= k ? s : `${s.slice(0, k)}…`
}

export function useSettingsPageState() {
  const { refresh: refreshCapabilities } = usePipelineCapabilities()

  const [providers, setProviders] = useState<ModelProvider[]>(MODEL_PROVIDERS)
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  const [settings, setSettings] = useState<SystemSettings | null>(null)
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [backendMeta, setBackendMeta] = useState<BackendMeta | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState<SaveMessage | null>(null)
  const [lastUpdatedKeys, setLastUpdatedKeys] = useState<string[]>([])
  const [editedSettings, setEditedSettings] = useState<Partial<SystemSettings>>({})

  const [ltrModels, setLtrModels] = useState<LTRModelInfo[]>([])
  const [ltrLoading, setLtrLoading] = useState(false)
  const [ltrError, setLtrError] = useState<string | null>(null)
  const [ltrMessage, setLtrMessage] = useState<SaveMessage | null>(null)
  const [ltrUploading, setLtrUploading] = useState(false)
  const [ltrUploadModelFile, setLtrUploadModelFile] = useState<File | null>(null)
  const [ltrUploadManifestFile, setLtrUploadManifestFile] = useState<File | null>(null)
  const [ltrUploadResetKey, setLtrUploadResetKey] = useState(0)
  const [ltrBusyModelId, setLtrBusyModelId] = useState<string | null>(null)

  const ragMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_RAG, settings?.rag, editedSettings.rag),
    [settings?.rag, editedSettings.rag]
  )
  const urlIngestMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_URL_INGEST, settings?.url_ingest, editedSettings.url_ingest),
    [settings?.url_ingest, editedSettings.url_ingest]
  )
  const governanceMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_GOVERNANCE, settings?.governance, editedSettings.governance),
    [settings?.governance, editedSettings.governance]
  )
  const observabilityMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_OBSERVABILITY, settings?.observability, editedSettings.observability),
    [settings?.observability, editedSettings.observability]
  )
  const safetyMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_SAFETY, settings?.safety, editedSettings.safety),
    [settings?.safety, editedSettings.safety]
  )
  const chatMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_CHAT, settings?.chat, editedSettings.chat),
    [settings?.chat, editedSettings.chat]
  )
  const langGraphMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_LANGGRAPH, settings?.langgraph, editedSettings.langgraph),
    [settings?.langgraph, editedSettings.langgraph]
  )
  const navigationMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_NAVIGATION, settings?.navigation, editedSettings.navigation),
    [settings?.navigation, editedSettings.navigation]
  )
  const cacheMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_CACHE, settings?.cache, editedSettings.cache),
    [settings?.cache, editedSettings.cache]
  )
  const etl4llmMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_ETL4LLM, settings?.etl4llm, editedSettings.etl4llm),
    [settings?.etl4llm, editedSettings.etl4llm]
  )
  const markerMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_MARKER, settings?.marker, editedSettings.marker),
    [settings?.marker, editedSettings.marker]
  )
  const paddleVlMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_PADDLE_VL, settings?.paddle_vl, editedSettings.paddle_vl),
    [settings?.paddle_vl, editedSettings.paddle_vl]
  )
  const textInMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_TEXTIN, settings?.textin, editedSettings.textin),
    [settings?.textin, editedSettings.textin]
  )
  const magicPdfMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_MAGICPDF, settings?.magicpdf, editedSettings.magicpdf),
    [settings?.magicpdf, editedSettings.magicpdf]
  )

  const isGovernanceEnabled = governanceMerged.enabled
  const isPiiAnonymizeEnabled = governanceMerged.pii_anonymize
  const isSecretsRedactEnabled = governanceMerged.secrets_redact
  const isQuarantineOnDropEnabled = governanceMerged.quarantine_on_drop

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

  useEffect(() => {
    void loadSettings()
    void loadLtrModels()
  }, [])

  const registerLtrModel = async () => {
    if (!ltrUploadModelFile || !ltrUploadManifestFile) return
    setLtrUploading(true)
    setLtrMessage(null)
    try {
      await ltrApi.registerModel({
        modelFile: ltrUploadModelFile,
        manifestFile: ltrUploadManifestFile,
      })
      setLtrMessage({ type: 'success', text: '已注册 LTR 模型' })
      setLtrUploadModelFile(null)
      setLtrUploadManifestFile(null)
      setLtrUploadResetKey((key) => key + 1)
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

  const toggleFeature = (key: keyof FeatureFlags) => {
    setEditedSettings((prev) => {
      const currentFlags = mergeWithDefaults(
        DEFAULT_FEATURE_FLAGS,
        settings?.feature_flags,
        prev.feature_flags
      )
      return {
        ...prev,
        feature_flags: {
          ...currentFlags,
          [key]: !currentFlags[key],
        },
      }
    })
  }

  const getFeatureValue = (key: keyof FeatureFlags): boolean => {
    if (editedSettings.feature_flags && key in editedSettings.feature_flags) {
      return editedSettings.feature_flags[key]
    }
    return settings?.feature_flags?.[key] ?? false
  }

  const updateObservability = (patch: Partial<ObservabilityConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      observability: mergeConfig(
        mergeWithDefaults(DEFAULT_OBSERVABILITY, settings?.observability, prev.observability),
        patch
      ),
    }))
  }

  const updateSafety = (patch: Partial<SafetyConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      safety: mergeConfig(
        mergeWithDefaults(DEFAULT_SAFETY, settings?.safety, prev.safety),
        patch
      ),
    }))
  }

  const updateLangGraph = (patch: Partial<LangGraphConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      langgraph: mergeConfig(
        mergeWithDefaults(DEFAULT_LANGGRAPH, settings?.langgraph, prev.langgraph),
        patch
      ),
    }))
  }

  const updateNavigation = (patch: Partial<NavigationConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      navigation: mergeConfig(
        mergeWithDefaults(DEFAULT_NAVIGATION, settings?.navigation, prev.navigation),
        patch
      ),
    }))
  }

  const updateChat = (patch: Partial<ChatConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      chat: mergeConfig(mergeWithDefaults(DEFAULT_CHAT, settings?.chat, prev.chat), patch),
    }))
  }

  const updateCache = (patch: Partial<CacheConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      cache: mergeConfig(mergeWithDefaults(DEFAULT_CACHE, settings?.cache, prev.cache), patch),
    }))
  }

  const updateMagicPDF = (patch: Partial<MagicPDFConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      magicpdf: mergeConfig(
        mergeWithDefaults(DEFAULT_MAGICPDF, settings?.magicpdf, prev.magicpdf),
        patch
      ),
    }))
  }

  const updateEtl4Llm = (patch: Partial<Etl4LlmConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      etl4llm: mergeConfig(
        mergeWithDefaults(DEFAULT_ETL4LLM, settings?.etl4llm, prev.etl4llm),
        patch
      ),
    }))
  }

  const updateMarker = (patch: Partial<MarkerConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      marker: mergeConfig(mergeWithDefaults(DEFAULT_MARKER, settings?.marker, prev.marker), patch),
    }))
  }

  const updatePaddleVL = (patch: Partial<PaddleVLConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      paddle_vl: mergeConfig(
        mergeWithDefaults(DEFAULT_PADDLE_VL, settings?.paddle_vl, prev.paddle_vl),
        patch
      ),
    }))
  }

  const updateTextIn = (patch: Partial<TextInConfig>) => {
    setEditedSettings((prev) => ({
      ...prev,
      textin: mergeConfig(
        mergeWithDefaults(DEFAULT_TEXTIN, settings?.textin, prev.textin),
        patch
      ),
    }))
  }

  const updateRag = (patch: Partial<RagSettings>) => {
    setEditedSettings((prev) => ({
      ...prev,
      rag: mergeConfig(mergeWithDefaults(DEFAULT_RAG, settings?.rag, prev.rag), patch),
    }))
  }

  const updateUrlIngest = (patch: Partial<UrlIngestSettings>) => {
    setEditedSettings((prev) => ({
      ...prev,
      url_ingest: mergeConfig(
        mergeWithDefaults(DEFAULT_URL_INGEST, settings?.url_ingest, prev.url_ingest),
        patch
      ),
    }))
  }

  const updateGovernance = (patch: Partial<GovernanceSettings>) => {
    setEditedSettings((prev) => ({
      ...prev,
      governance: mergeConfig(
        mergeWithDefaults(DEFAULT_GOVERNANCE, settings?.governance, prev.governance),
        patch
      ),
    }))
  }

  const hasChanges = Object.keys(editedSettings).length > 0

  useEffect(() => {
    if (!hasChanges) return

    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
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
      prev.map((provider) =>
        provider.id === providerId ? { ...provider, isConfigured: true, config } : provider
      )
    )

    const provider = providers.find((item) => item.id === providerId)
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

  const groupedProviders = useMemo(() => {
    const groups: Record<ProviderCategory, ModelProvider[]> = {
      model: [],
      embedding: [],
      reranker: [],
    }
    providers.forEach((provider) => {
      groups[provider.category].push(provider)
    })
    return groups
  }, [providers])

  const refreshAll = () => {
    void loadSettings()
    void loadLtrModels()
  }

  const refreshLtrModels = () => {
    void loadLtrModels()
  }

  return {
    activateLtrModel,
    backendMeta,
    cacheMerged,
    chatMerged,
    dialogOpen,
    editedFeatureFlags: editedSettings.feature_flags,
    etl4llmMerged,
    formatBytes,
    formatTime,
    getFeatureValue,
    governanceMerged,
    groupedProviders,
    handleConfigure,
    handleSaveConfig,
    hasChanges,
    isGovernanceEnabled,
    isPiiAnonymizeEnabled,
    isQuarantineOnDropEnabled,
    isSecretsRedactEnabled,
    langGraphMerged,
    lastUpdatedKeys,
    loadError,
    loading,
    ltrBusyModelId,
    ltrError,
    ltrLoading,
    ltrMessage,
    ltrModels,
    ltrUploadReady: Boolean(ltrUploadModelFile && ltrUploadManifestFile),
    ltrUploadResetKey,
    ltrUploading,
    magicPdfMerged,
    markerMerged,
    navigationMerged,
    observabilityMerged,
    paddleVlMerged,
    textInMerged,
    ragMerged,
    refreshAll,
    refreshLtrModels,
    registerLtrModel,
    rollbackLtrModel,
    saveMessage,
    saveSettings,
    saving,
    selectedProvider,
    setDialogOpen,
    setLtrUploadManifestFile,
    setLtrUploadModelFile,
    shortId,
    status,
    toggleFeature,
    updateCache,
    updateChat,
    updateEtl4Llm,
    updateGovernance,
    updateLangGraph,
    updateNavigation,
    updateMagicPDF,
    updateMarker,
    updateObservability,
    updatePaddleVL,
    updateTextIn,
    updateRag,
    updateSafety,
    updateUrlIngest,
    urlIngestMerged,
    safetyMerged,
  }
}
