'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { formatApiError } from '@/lib/api-errors'
import {
  metaApi,
  settingsApi,
  type BackendMetaDetails,
  type CacheConfig,
  type ChatConfig,
  type DifyExternalKnowledgeConfig,
  type Etl4LlmConfig,
  type FeatureFlags,
  type LangGraphConfig,
  type MagicPDFConfig,
  type MarkerConfig,
  type MinerUConfig,
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

type EditableSettings = Partial<Omit<SystemSettings, 'url_ingest' | 'minio'>>
const AUTOSAVE_DELAY_MS = 500

type RagSettings = NonNullable<SystemSettings['rag']>
type GovernanceSettings = NonNullable<SystemSettings['governance']>
type DifyExternalKnowledgeSettings = NonNullable<SystemSettings['dify_external_knowledge']>
type DoclingConfig = NonNullable<SystemSettings['docling']>

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

const DEFAULT_DIFY_EXTERNAL_KNOWLEDGE: DifyExternalKnowledgeConfig = {
  enabled: false,
  api_keys: '',
  tenant_id: '',
  account_id: 'system:dify',
  knowledge_map_json: '',
  top_k_max: 50,
  endpoint_path: '/api/v1/integrations/dify/retrieval',
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
  show_image_in_answer: true,
  image_append_max: 3,
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
  models_dir: '',
  device_mode: 'cpu',
  keep_artifacts: false,
}

const DEFAULT_MINERU: MinerUConfig = {
  api_token: '',
  api_base: 'https://mineru.net/api/v4',
  model_version: 'vlm',
  backend: 'pipeline',
  local_server_url: '',
  vl_server: '',
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

const DEFAULT_DOCLING: DoclingConfig = {
  api_url: '',
  api_key: '',
  request_timeout_sec: 600,
  health_timeout_sec: 5,
  http_trust_env: false,
  ocr_enabled: true,
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

function normalizeApiBase(value: unknown): string {
  return trimmedPrimitiveString(value).toLowerCase()
}

function providerHasModel(provider: ModelProvider, modelName: string): boolean {
  const target = String(modelName || '').trim().toLowerCase()
  if (!target) return false
  return provider.models.some((model) => String(model.name || '').trim().toLowerCase() === target)
}

function findProviderIdByModel(
  providers: ModelProvider[],
  category: ProviderCategory,
  modelName: string
): string | null {
  return (
    providers.find(
      (provider) =>
        provider.category === category && providerHasModel(provider, modelName)
    )?.id ?? null
  )
}

function resolveLlmProviderId(
  providers: ModelProvider[],
  llm: SystemSettings['llm'] | null | undefined
): string | null {
  if (!llm) return null
  const base = normalizeApiBase(llm.api_base)
  const model = trimmedPrimitiveString(llm.model)

  if (base.includes('dashscope.aliyuncs.com')) return 'qwen'
  if (base.includes('api.openai.com')) return 'openai'
  if (base.includes('anthropic.com')) return 'anthropic'
  if (base.includes('api.deepseek.com')) return 'deepseek'
  if (base.includes('bigmodel.cn')) return 'zhipu'
  if (base.includes('moonshot.cn')) return 'moonshot'
  if (base.includes('volces.com')) return 'ark'
  if (base.includes('lingyiwanwu.com')) return 'lingyiwanwu'
  if (base.includes('baidubce.com')) return 'qianfan'
  if (base.includes('siliconflow.cn')) return 'siliconflow'
  if (base.includes('openrouter.ai')) return 'openrouter'
  if (base.includes('together.xyz')) return 'together'
  if (base.includes('localhost:11434')) return 'ollama'

  return findProviderIdByModel(providers, 'model', model)
}

function resolveEmbeddingProviderId(
  providers: ModelProvider[],
  embedding: SystemSettings['embedding'] | null | undefined
): string | null {
  if (!embedding) return null
  const base = normalizeApiBase(embedding.api_base)
  const provider = trimmedPrimitiveString(embedding.provider).toLowerCase()
  const model = trimmedPrimitiveString(embedding.model)

  if (provider === 'dashscope' || base.includes('dashscope.aliyuncs.com')) {
    return 'qwen-embedding'
  }
  if (provider === 'local' || /bge|text2vec|nomic|mxbai/i.test(model)) {
    return 'local-embedding'
  }
  if (base.includes('api.openai.com')) return 'openai-embedding'

  return findProviderIdByModel(providers, 'embedding', model)
    ?? (provider === 'openai' || provider === 'openai_compatible' ? 'openai-embedding' : null)
}

function hydrateProvidersFromSettings(
  providers: ModelProvider[],
  settings: SystemSettings | null
): ModelProvider[] {
  const next: ModelProvider[] = providers.map((provider) => ({
    ...provider,
    isConfigured: false,
    config: undefined as ProviderConfig | undefined,
  }))

  if (!settings) return next

  const llmProviderId = resolveLlmProviderId(next, settings.llm)
  if (llmProviderId) {
    const llmConfig: ProviderConfig = {
      apiKey: settings.llm.api_key || '',
      apiBase: settings.llm.api_base || '',
      model: settings.llm.model || '',
      temperature: settings.llm.temperature,
      timeout: settings.llm.timeout,
    }
    const provider = next.find((item) => item.id === llmProviderId)
    if (provider) {
      provider.isConfigured = Boolean(llmConfig.model || llmConfig.apiBase || llmConfig.apiKey)
      provider.config = llmConfig
    }
  }

  const embeddingProviderId = resolveEmbeddingProviderId(next, settings.embedding)
  if (embeddingProviderId) {
    const embeddingConfig: ProviderConfig = {
      apiKey: settings.embedding.api_key || '',
      apiBase: settings.embedding.api_base || '',
      model: settings.embedding.model || '',
    }
    const provider = next.find((item) => item.id === embeddingProviderId)
    if (provider) {
      provider.isConfigured = Boolean(
        embeddingConfig.model || embeddingConfig.apiBase || embeddingConfig.apiKey
      )
      provider.config = embeddingConfig
    }
  }

  return next
}

function resolveEmbeddingProvider(providerId: string): string {
  const pid = String(providerId || '').trim().toLowerCase()
  if (pid === 'qwen-embedding') return 'dashscope'
  if (pid === 'local-embedding') return 'local'
  return 'openai_compatible'
}

export function useSettingsPageState() {
  const { refresh: refreshCapabilities } = usePipelineCapabilities()

  const [providers, setProviders] = useState<ModelProvider[]>(MODEL_PROVIDERS)
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  const [settings, setSettings] = useState<SystemSettings | null>(null)
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [backendMeta, setBackendMeta] = useState<BackendMetaDetails | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [editedSettings, setEditedSettings] = useState<EditableSettings>({})
  const pendingSettings = useRef<EditableSettings>({})
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const requestRunning = useRef(false)
  const saveFailed = useRef(false)
  const mounted = useRef(false)

  const ragMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_RAG, settings?.rag, editedSettings.rag),
    [settings?.rag, editedSettings.rag]
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
  const difyExternalKnowledgeMerged = useMemo(
    () =>
      mergeWithDefaults(
        DEFAULT_DIFY_EXTERNAL_KNOWLEDGE,
        settings?.dify_external_knowledge,
        editedSettings.dify_external_knowledge
      ),
    [settings?.dify_external_knowledge, editedSettings.dify_external_knowledge]
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
  const doclingMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_DOCLING, settings?.docling, editedSettings.docling),
    [settings?.docling, editedSettings.docling]
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
  const mineruMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_MINERU, settings?.mineru, editedSettings.mineru),
    [settings?.mineru, editedSettings.mineru]
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
        metaApi.details().catch(() => null),
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

  useEffect(() => {
    void loadSettings()
  }, [])

  useEffect(() => {
    setProviders(hydrateProvidersFromSettings(MODEL_PROVIDERS, settings))
  }, [settings])

  const flushSettings = useCallback(async () => {
    if (requestRunning.current || Object.keys(pendingSettings.current).length === 0) return
    requestRunning.current = true
    saveFailed.current = false
    if (mounted.current) {
      setSaving(true)
      setSaveError(null)
    }
    try {
      while (Object.keys(pendingSettings.current).length > 0) {
        const submitted = pendingSettings.current
        const result = await settingsApi.update(submitted)
        if (!result.success) throw new Error(result.message || '保存失败')
        const confirmed = await settingsApi.get()

        // A newer edit creates a new group object. Acknowledge only the groups
        // that still match this request, leaving later edits in the queue.
        const remaining = Object.fromEntries(
          Object.entries(pendingSettings.current).filter(
            ([key, value]) => value !== submitted[key as keyof EditableSettings]
          )
        ) as EditableSettings
        pendingSettings.current = remaining
        if (mounted.current) {
          setSettings(confirmed)
          setEditedSettings(remaining)
        }
        if (saveTimer.current) break
      }
      if (mounted.current) {
        void settingsApi.getStatus().then(setStatus).catch(() => null)
        void refreshCapabilities().catch(() => null)
      }
    } catch (error) {
      saveFailed.current = true
      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = null
      if (mounted.current) setSaveError(formatApiError(error, '保存失败'))
    } finally {
      requestRunning.current = false
      if (mounted.current) setSaving(false)
    }
  }, [refreshCapabilities])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = null
      if (!saveFailed.current) void flushSettings()
    }
  }, [flushSettings])

  const queueSettingsEdit = (edit: (current: EditableSettings) => EditableSettings, immediate: boolean) => {
    const next = edit(pendingSettings.current)
    pendingSettings.current = next
    setEditedSettings(next)
    setSaveError(null)
    saveFailed.current = false
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = null
    if (immediate) {
      void flushSettings()
    } else {
      saveTimer.current = setTimeout(() => {
        saveTimer.current = null
        void flushSettings()
      }, AUTOSAVE_DELAY_MS)
    }
  }

  function updateSection<K extends keyof EditableSettings>(
    key: K,
    defaults: SystemSettings[K],
    patch: Partial<SystemSettings[K]>
  ) {
    queueSettingsEdit((prev) => ({
      ...prev,
      [key]: mergeConfig(mergeWithDefaults(defaults, settings?.[key], prev[key]), patch),
    }), Object.values(patch).some((value) => typeof value === 'boolean' || Array.isArray(value)))
  }

  const retrySave = () => {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = null
    return flushSettings()
  }

  const toggleFeature = (key: keyof FeatureFlags) => {
    queueSettingsEdit((prev) => {
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
    }, true)
  }

  const getFeatureValue = (key: keyof FeatureFlags): boolean => {
    if (editedSettings.feature_flags && key in editedSettings.feature_flags) {
      return editedSettings.feature_flags[key]
    }
    return settings?.feature_flags?.[key] ?? false
  }

  const updateObservability = (patch: Partial<ObservabilityConfig>) => {
    updateSection('observability', DEFAULT_OBSERVABILITY, patch)
  }

  const updateSafety = (patch: Partial<SafetyConfig>) => {
    updateSection('safety', DEFAULT_SAFETY, patch)
  }

  const updateLangGraph = (patch: Partial<LangGraphConfig>) => {
    updateSection('langgraph', DEFAULT_LANGGRAPH, patch)
  }

  const updateNavigation = (patch: Partial<NavigationConfig>) => {
    updateSection('navigation', DEFAULT_NAVIGATION, patch)
  }

  const updateDifyExternalKnowledge = (patch: Partial<DifyExternalKnowledgeSettings>) => {
    updateSection('dify_external_knowledge', DEFAULT_DIFY_EXTERNAL_KNOWLEDGE, patch)
  }

  const updateChat = (patch: Partial<ChatConfig>) => {
    updateSection('chat', DEFAULT_CHAT, patch)
  }

  const updateCache = (patch: Partial<CacheConfig>) => {
    updateSection('cache', DEFAULT_CACHE, patch)
  }

  const updateMagicPDF = (patch: Partial<MagicPDFConfig>) => {
    updateSection('magicpdf', DEFAULT_MAGICPDF, patch)
  }

  const updateMinerU = (patch: Partial<MinerUConfig>) => {
    updateSection('mineru', DEFAULT_MINERU, patch)
  }

  const updateEtl4Llm = (patch: Partial<Etl4LlmConfig>) => {
    updateSection('etl4llm', DEFAULT_ETL4LLM, patch)
  }

  const updateMarker = (patch: Partial<MarkerConfig>) => {
    updateSection('marker', DEFAULT_MARKER, patch)
  }

  const updateDocling = (patch: Partial<DoclingConfig>) => {
    updateSection('docling', DEFAULT_DOCLING, patch)
  }

  const updatePaddleVL = (patch: Partial<PaddleVLConfig>) => {
    updateSection('paddle_vl', DEFAULT_PADDLE_VL, patch)
  }

  const updateTextIn = (patch: Partial<TextInConfig>) => {
    updateSection('textin', DEFAULT_TEXTIN, patch)
  }

  const updateRag = (patch: Partial<RagSettings>) => {
    updateSection('rag', DEFAULT_RAG, patch)
  }

  const updateGovernance = (patch: Partial<GovernanceSettings>) => {
    updateSection('governance', DEFAULT_GOVERNANCE, patch)
  }

  const hasChanges = Object.keys(editedSettings).length > 0

  useEffect(() => {
    if (!hasChanges) return

    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault()
    }

    globalThis.window.addEventListener('beforeunload', handler)
    return () => globalThis.window.removeEventListener('beforeunload', handler)
  }, [hasChanges])

  const handleConfigure = (provider: ModelProvider) => {
    setSelectedProvider(provider)
    setDialogOpen(true)
  }

  const handleSaveConfig = async (providerId: string, config: ProviderConfig) => {
    const provider = providers.find((item) => item.id === providerId)
    if (!provider) return

    if (provider.category === 'model' || provider.category === 'embedding') {
      const payload: EditableSettings =
        provider.category === 'model'
          ? {
              llm: {
                api_key: config.apiKey || '',
                api_base: config.apiBase || '',
                model: config.model || '',
                temperature: config.temperature ?? 0.7,
                timeout: config.timeout ?? 60,
                max_retries: 3,
              },
            }
          : {
              embedding: {
                provider: resolveEmbeddingProvider(provider.id),
                model: config.model || '',
                api_key: config.apiKey || '',
                api_base: config.apiBase || '',
              },
            }

      queueSettingsEdit((prev) => ({ ...prev, ...payload }), true)
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

  return {
    backendMeta,
    cacheMerged,
    chatMerged,
    dialogOpen,
    difyExternalKnowledgeMerged,
    doclingMerged,
    etl4llmMerged,
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
    loadError,
    loading,
    magicPdfMerged,
    markerMerged,
    mineruMerged,
    navigationMerged,
    observabilityMerged,
    paddleVlMerged,
    textInMerged,
    ragMerged,
    saveError,
    retrySave,
    saving,
    selectedProvider,
    setDialogOpen,
    status,
    toggleFeature,
    updateCache,
    updateChat,
    updateDifyExternalKnowledge,
    updateDocling,
    updateEtl4Llm,
    updateGovernance,
    updateLangGraph,
    updateNavigation,
    updateMagicPDF,
    updateMarker,
    updateMinerU,
    updateObservability,
    updatePaddleVL,
    updateTextIn,
    updateRag,
    updateSafety,
    safetyMerged,
  }
}
