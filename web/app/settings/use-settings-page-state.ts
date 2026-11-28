'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { formatApiError } from '@/lib/api-errors'
import { AUTH_SCOPE_CHANGED_EVENT, getAuthSessionKey } from '@/lib/auth-storage'
import { metaApi, type BackendMetaDetails } from '@/lib/api/meta'
import { settingsApi } from '@/lib/api/settings'
import {
  type CacheConfig,
  type ChatConfig,
  type DifyExternalKnowledgeConfig,
  type DoclingConfig,
  type Etl4LlmConfig,
  type FeatureFlags,
  type GovernanceConfig,
  type LangGraphConfig,
  type MagicPDFConfig,
  type MarkerConfig,
  type MinerUConfig,
  type NavigationConfig,
  type ObservabilityConfig,
  type PaddleVLConfig,
  type RAGConfig,
  type SafetyConfig,
  type SystemSettings,
  type SystemStatus,
  type TextInConfig,
} from '@/types/settings'
import {
  MODEL_PROVIDERS,
  type ModelConfigSubmission,
  type ModelProvider,
  type ProviderCategory,
  type ProviderConfig,
} from '@/types/models'

type EditableSettings = Partial<Omit<SystemSettings, 'url_ingest' | 'minio'>>
const AUTOSAVE_DELAY_MS = 500

function mergeWithDefaults<T extends object>(
  defaults: T,
  current: Partial<T> | null | undefined,
  edited: Partial<T> | null | undefined,
): T {
  return {
    ...defaults,
    ...current,
    ...edited,
  }
}

function retireSubmittedSettings(current: Partial<SystemSettings>, submitted: Partial<SystemSettings>) {
  const next = { ...current }
  for (const key of Object.keys(submitted) as Array<keyof SystemSettings>) {
    if (current[key] === submitted[key]) delete next[key]
  }
  return next
}

function isCurrentPageSession(owner: { active: boolean }, sessionKey: string): boolean {
  return owner.active && sessionKey === getAuthSessionKey()
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
  top_k_max: 5,
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

const DEFAULT_RAG: RAGConfig = {
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

const DEFAULT_GOVERNANCE: GovernanceConfig = {
  enabled: false,
  pii_anonymize: false,
  secrets_redact: false,
  quarantine_on_drop: false,
}

const DEFAULT_MAGICPDF: MagicPDFConfig = {
  api_url: '',
  request_timeout_sec: 600,
  max_concurrent_jobs: 1,
  cli: 'magic-pdf',
  method: 'auto',
  lang: '',
  debug: false,
  timeout_sec: 600,
  models_dir: '',
  device_mode: '',
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
  pipeline_version: 'v1.5',
  mode: 'doc_parser',
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

function findProviderIdByModel(
  providers: ModelProvider[],
  category: ProviderCategory,
  modelName: string,
): string | null {
  const target = modelName.trim().toLowerCase()
  if (target === '') return null
  return (
    providers.find(
      (provider) =>
        provider.category === category && provider.models.some((model) => model.name.trim().toLowerCase() === target),
    )?.id ?? null
  )
}

function resolveLlmProviderId(
  providers: ModelProvider[],
  llm: SystemSettings['llm'] | null | undefined,
): string | null {
  if (!llm) return null
  if (llm.api_base !== undefined) {
    const base = llm.api_base.trim().toLowerCase()
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
  }

  return findProviderIdByModel(providers, 'model', llm.model)
}

function resolveEmbeddingProviderId(
  providers: ModelProvider[],
  embedding: SystemSettings['embedding'] | null | undefined,
): string | null {
  if (!embedding) return null
  const base = embedding.api_base.trim().toLowerCase()
  const provider = embedding.provider.trim().toLowerCase()

  if (provider === 'local') return null
  if (provider === 'ollama') return 'ollama-embedding'
  if (provider === 'dashscope' || base.includes('dashscope.aliyuncs.com')) {
    return 'qwen-embedding'
  }
  if (base.includes('api.openai.com')) return 'openai-embedding'

  return (
    findProviderIdByModel(providers, 'embedding', embedding.model) ??
    (provider === 'openai' || provider === 'openai_compatible' ? 'openai-embedding' : null)
  )
}

function hydrateProvidersFromSettings(providers: ModelProvider[], settings: SystemSettings | null): ModelProvider[] {
  const next = providers.map<ModelProvider>((provider) => ({
    ...provider,
    isConfigured: false,
    config: undefined,
  }))

  if (!settings) return next

  const llmConfig: ProviderConfig = {
    apiKey: settings.llm.api_key,
    apiBase: settings.llm.api_base,
    model: settings.llm.model,
    temperature: settings.llm.temperature,
    timeout: settings.llm.timeout,
  }
  if (settings.llm.model !== '' || settings.llm.api_base !== '' || settings.llm.api_key !== '') {
    const providerId = resolveLlmProviderId(next, settings.llm)
    const provider = next.find((item) => item.id === providerId)
    if (provider) {
      provider.isConfigured = true
      provider.config = llmConfig
    } else {
      next.unshift({
        id: 'custom-chat',
        name: '自定义聊天模型',
        description: '当前保存的聊天模型配置',
        icon: 'model',
        color: 'slate',
        category: 'model',
        isConfigured: true,
        models: [],
        config: llmConfig,
      })
    }
  }

  const embeddingProviderId = resolveEmbeddingProviderId(next, settings.embedding)
  if (embeddingProviderId) {
    const embeddingConfig: ProviderConfig = {
      apiKey: settings.embedding.api_key,
      apiBase: settings.embedding.api_base,
      model: settings.embedding.model,
    }
    const provider = next.find((item) => item.id === embeddingProviderId)
    if (provider) {
      provider.isConfigured = Boolean(embeddingConfig.model || embeddingConfig.apiBase || embeddingConfig.apiKey)
      provider.config = embeddingConfig
    }
  }

  return next
}

function resolveEmbeddingProvider(providerId: string): string {
  const pid = providerId.trim().toLowerCase()
  if (pid === 'qwen-embedding') return 'dashscope'
  if (pid === 'ollama-embedding') return 'ollama'
  if (pid === 'local-embedding') throw new Error('本地模型推理已停用，请选择向量模型服务')
  return 'openai_compatible'
}

export function useSettingsPageState() {
  const { refresh: refreshCapabilities } = usePipelineCapabilities()

  const [selectedProvider, setSelectedProvider] = useState<ModelProvider | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  const [settings, setSettings] = useState<SystemSettings | null>(null)
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [statusLoading, setStatusLoading] = useState(false)
  const [backendMeta, setBackendMeta] = useState<BackendMetaDetails | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [editedSettings, setEditedSettings] = useState<EditableSettings>({})
  const pendingSettings = useRef<EditableSettings>({})
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const requestRunning = useRef<symbol | null>(null)
  const saveFailed = useRef(false)
  const pageOwnerRef = useRef({ active: false })
  const settingsLoadRef = useRef<AbortController | null>(null)
  const statusReadRef = useRef<AbortController | null>(null)

  const providers = useMemo(() => hydrateProvidersFromSettings(MODEL_PROVIDERS, settings), [settings])
  const ragMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_RAG, settings?.rag, editedSettings.rag),
    [settings?.rag, editedSettings.rag],
  )
  const governanceMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_GOVERNANCE, settings?.governance, editedSettings.governance),
    [settings?.governance, editedSettings.governance],
  )
  const observabilityMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_OBSERVABILITY, settings?.observability, editedSettings.observability),
    [settings?.observability, editedSettings.observability],
  )
  const safetyMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_SAFETY, settings?.safety, editedSettings.safety),
    [settings?.safety, editedSettings.safety],
  )
  const chatMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_CHAT, settings?.chat, editedSettings.chat),
    [settings?.chat, editedSettings.chat],
  )
  const langGraphMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_LANGGRAPH, settings?.langgraph, editedSettings.langgraph),
    [settings?.langgraph, editedSettings.langgraph],
  )
  const navigationMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_NAVIGATION, settings?.navigation, editedSettings.navigation),
    [settings?.navigation, editedSettings.navigation],
  )
  const difyExternalKnowledgeMerged = useMemo(
    () =>
      mergeWithDefaults(
        DEFAULT_DIFY_EXTERNAL_KNOWLEDGE,
        settings?.dify_external_knowledge,
        editedSettings.dify_external_knowledge,
      ),
    [settings?.dify_external_knowledge, editedSettings.dify_external_knowledge],
  )
  const cacheMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_CACHE, settings?.cache, editedSettings.cache),
    [settings?.cache, editedSettings.cache],
  )
  const etl4llmMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_ETL4LLM, settings?.etl4llm, editedSettings.etl4llm),
    [settings?.etl4llm, editedSettings.etl4llm],
  )
  const markerMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_MARKER, settings?.marker, editedSettings.marker),
    [settings?.marker, editedSettings.marker],
  )
  const doclingMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_DOCLING, settings?.docling, editedSettings.docling),
    [settings?.docling, editedSettings.docling],
  )
  const paddleVlMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_PADDLE_VL, settings?.paddle_vl, editedSettings.paddle_vl),
    [settings?.paddle_vl, editedSettings.paddle_vl],
  )
  const textInMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_TEXTIN, settings?.textin, editedSettings.textin),
    [settings?.textin, editedSettings.textin],
  )
  const magicPdfMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_MAGICPDF, settings?.magicpdf, editedSettings.magicpdf),
    [settings?.magicpdf, editedSettings.magicpdf],
  )
  const mineruMerged = useMemo(
    () => mergeWithDefaults(DEFAULT_MINERU, settings?.mineru, editedSettings.mineru),
    [settings?.mineru, editedSettings.mineru],
  )

  const isGovernanceEnabled = governanceMerged.enabled
  const isPiiAnonymizeEnabled = governanceMerged.pii_anonymize
  const isSecretsRedactEnabled = governanceMerged.secrets_redact
  const isQuarantineOnDropEnabled = governanceMerged.quarantine_on_drop

  const refreshSystemStatus = useCallback(async (owner: { active: boolean }, sessionKey: string) => {
    if (!isCurrentPageSession(owner, sessionKey)) return
    statusReadRef.current?.abort()
    const read = new AbortController()
    statusReadRef.current = read
    const isCurrent = () => statusReadRef.current === read && isCurrentPageSession(owner, sessionKey)
    setStatusLoading(true)
    setStatusError(null)
    try {
      const nextStatus = await settingsApi.getStatus({ signal: read.signal })
      if (isCurrent()) setStatus(nextStatus)
    } catch (error) {
      if (isCurrent()) setStatusError(formatApiError(error, '读取服务状态失败'))
    } finally {
      if (isCurrent()) {
        statusReadRef.current = null
        setStatusLoading(false)
      }
    }
  }, [])

  const startSettingsRead = useCallback(() => {
    settingsLoadRef.current?.abort()
    const load = new AbortController()
    settingsLoadRef.current = load
    return load
  }, [])

  const loadSettings = useCallback(async () => {
    const owner = pageOwnerRef.current
    if (!owner.active) return
    const sessionKey = getAuthSessionKey()
    const load = startSettingsRead()
    const isCurrent = () => settingsLoadRef.current === load && isCurrentPageSession(owner, sessionKey)
    setLoading(true)
    setLoadError(null)
    void refreshSystemStatus(owner, sessionKey)
    void metaApi.details({ signal: load.signal }).then(
      (metadata) => {
        if (isCurrent()) setBackendMeta(metadata)
      },
      () => {
        if (isCurrent()) setBackendMeta(null)
      },
    )
    try {
      const settingsData = await settingsApi.get({ signal: load.signal })
      if (!isCurrent()) return
      setSettings(settingsData)
    } catch (error) {
      if (isCurrent()) setLoadError(formatApiError(error, '加载失败'))
    } finally {
      if (isCurrent()) setLoading(false)
    }
  }, [refreshSystemStatus, startSettingsRead])

  const reloadAfterSave = useCallback(
    async (canPublish: () => boolean, submitted: Partial<SystemSettings>) => {
      if (!canPublish()) return
      setSettings((current) => (current === null ? null : { ...current, ...submitted }))
      const load = startSettingsRead()
      const isCurrent = () => settingsLoadRef.current === load && canPublish()
      try {
        const confirmed = await settingsApi.get({ signal: load.signal })
        if (isCurrent()) {
          setSettings(confirmed)
          setLoadError(null)
        }
      } catch (error) {
        if (isCurrent()) {
          setLoadError(`配置已保存，读取最新配置失败。${formatApiError(error, '请求未返回最新配置')}`)
        }
      } finally {
        if (isCurrent()) setLoading(false)
      }
    },
    [startSettingsRead],
  )

  const flushSettings = useCallback(async () => {
    if (requestRunning.current || Object.keys(pendingSettings.current).length === 0) return
    const owner = pageOwnerRef.current
    const sessionKey = getAuthSessionKey()
    const write = Symbol()
    requestRunning.current = write
    const canPersist = () =>
      requestRunning.current === write && pageOwnerRef.current === owner && getAuthSessionKey() === sessionKey
    const canPublish = () => canPersist() && owner.active
    saveFailed.current = false
    if (canPublish()) {
      setSaving(true)
      setSaveError(null)
    }
    try {
      while (Object.keys(pendingSettings.current).length > 0) {
        const submitted = pendingSettings.current
        const result = await settingsApi.update(submitted)
        if (!canPersist()) return
        if (!result.success) throw new Error(result.message)
        await reloadAfterSave(canPublish, submitted)
        if (!canPersist()) return

        // A newer edit creates a new group object. Acknowledge only the groups
        // that still match this request, leaving later edits in the queue.
        const remaining = retireSubmittedSettings(pendingSettings.current, submitted)
        pendingSettings.current = remaining
        if (canPublish()) setEditedSettings(remaining)
        if (saveTimer.current) break
      }
      if (canPublish()) {
        void refreshSystemStatus(owner, sessionKey)
        void refreshCapabilities()
      }
    } catch (error) {
      if (!canPersist()) return
      saveFailed.current = true
      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = null
      if (canPublish()) setSaveError(formatApiError(error, '保存失败'))
    } finally {
      if (requestRunning.current === write) {
        requestRunning.current = null
        if (owner.active) setSaving(false)
      }
    }
  }, [refreshCapabilities, refreshSystemStatus, reloadAfterSave])

  useEffect(() => {
    const cancelReads = () => {
      settingsLoadRef.current?.abort()
      settingsLoadRef.current = null
      statusReadRef.current?.abort()
      statusReadRef.current = null
    }
    pageOwnerRef.current = { active: true }
    void loadSettings()
    const onScopeChanged = () => {
      pageOwnerRef.current.active = false
      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = null
      cancelReads()
      requestRunning.current = null
      pendingSettings.current = {}
      saveFailed.current = false
      setSettings(null)
      setStatus(null)
      setBackendMeta(null)
      setEditedSettings({})
      setSaving(false)
      setSaveError(null)
      setSelectedProvider(null)
      setDialogOpen(false)
      pageOwnerRef.current = { active: true }
      void loadSettings()
    }
    window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, onScopeChanged)
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = null
      if (!saveFailed.current) void flushSettings()
      pageOwnerRef.current.active = false
      cancelReads()
      window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, onScopeChanged)
    }
  }, [flushSettings, loadSettings])

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
    patch: Partial<SystemSettings[K]>,
  ) {
    queueSettingsEdit(
      (prev) => ({
        ...prev,
        [key]: { ...mergeWithDefaults(defaults, settings?.[key], prev[key]), ...patch },
      }),
      Object.values(patch).some((value) => typeof value === 'boolean' || Array.isArray(value)),
    )
  }

  const retrySave = () => {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = null
    return flushSettings()
  }

  const toggleFeature = (key: keyof FeatureFlags) => {
    queueSettingsEdit((prev) => {
      const currentFlags = mergeWithDefaults(DEFAULT_FEATURE_FLAGS, settings?.feature_flags, prev.feature_flags)
      return {
        ...prev,
        feature_flags: {
          ...currentFlags,
          [key]: !currentFlags[key],
        },
      }
    }, true)
  }

  const getFeatureValue = (key: keyof FeatureFlags): boolean =>
    editedSettings.feature_flags?.[key] ?? settings?.feature_flags?.[key] ?? DEFAULT_FEATURE_FLAGS[key]

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

  const updateDifyExternalKnowledge = (patch: Partial<DifyExternalKnowledgeConfig>) => {
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

  const updateRag = (patch: Partial<RAGConfig>) => {
    updateSection('rag', DEFAULT_RAG, patch)
  }

  const updateGovernance = (patch: Partial<GovernanceConfig>) => {
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
    if (requestRunning.current) {
      setSaveError('配置正在保存，请完成后再修改模型配置。')
      return
    }
    setSelectedProvider(provider)
    setDialogOpen(true)
  }

  const handleSaveConfig = async (providerId: string, config: ModelConfigSubmission) => {
    const provider = providers.find((item) => item.id === providerId)
    if (!provider || settings === null || !pageOwnerRef.current.active) {
      throw new Error('当前模型配置已变化，请重新打开对话框')
    }
    if (requestRunning.current) return

    if (provider.category === 'model' || provider.category === 'embedding') {
      const connection = {
        api_key: config.apiKey,
        api_base: config.apiBase,
        model: config.model,
      }
      const payload: EditableSettings =
        provider.category === 'model'
          ? {
              llm: {
                ...connection,
                temperature: config.temperature ?? settings.llm.temperature,
                timeout: config.timeout ?? settings.llm.timeout,
                max_retries: settings.llm.max_retries,
              },
            }
          : {
              embedding: {
                ...connection,
                provider: resolveEmbeddingProvider(provider.id),
              },
            }

      const owner = pageOwnerRef.current
      const sessionKey = getAuthSessionKey()
      const operation = Symbol()
      requestRunning.current = operation
      const isCurrent = () => requestRunning.current === operation && isCurrentPageSession(owner, sessionKey)
      setSaving(true)
      try {
        const result = await settingsApi.update(payload)
        if (!isCurrent()) return
        if (!result.success) throw new Error(result.message)
        await reloadAfterSave(isCurrent, payload)
        if (!isCurrent()) return
        setDialogOpen(false)
        void refreshSystemStatus(owner, sessionKey)
        void refreshCapabilities()
      } catch (error) {
        if (isCurrent()) throw error
      } finally {
        if (requestRunning.current === operation) {
          requestRunning.current = null
          if (owner.active) setSaving(false)
          if (
            !saveFailed.current &&
            !saveTimer.current &&
            pageOwnerRef.current === owner &&
            getAuthSessionKey() === sessionKey
          )
            void flushSettings()
        }
      }
    }
  }

  const groupedProviders = useMemo(() => {
    const groups: Record<'model' | 'embedding', ModelProvider[]> = {
      model: [],
      embedding: [],
    }
    providers.forEach((provider) => {
      if (provider.category !== 'reranker') groups[provider.category].push(provider)
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
    retiredEmbeddingModel:
      settings?.embedding.provider.trim().toLowerCase() === 'local' ? settings.embedding.model : null,
    handleConfigure,
    handleSaveConfig,
    hasChanges,
    hasLoadedSettings: settings !== null,
    isGovernanceEnabled,
    isPiiAnonymizeEnabled,
    isQuarantineOnDropEnabled,
    isSecretsRedactEnabled,
    langGraphMerged,
    loadError,
    loadSettings,
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
    statusError,
    statusLoading,
    reloadStatus: () => refreshSystemStatus(pageOwnerRef.current, getAuthSessionKey()),
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
