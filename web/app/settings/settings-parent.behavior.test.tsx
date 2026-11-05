// @vitest-environment happy-dom

import React, { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderHook, waitForAssertion } from '@/test/hook-harness'
import type { SystemSettings } from '@/types/settings'
import type { LTRModelInfo } from '@/lib/api/ltr'

const boundary = vi.hoisted(() => ({
  get: vi.fn(),
  status: vi.fn(),
  meta: vi.fn(),
  update: vi.fn(),
  listModels: vi.fn(),
  register: vi.fn(),
  activate: vi.fn(),
  rollback: vi.fn(),
  capabilities: vi.fn(),
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api', () => ({
  settingsApi: { get: boundary.get, getStatus: boundary.status, update: boundary.update },
  metaApi: { details: boundary.meta },
  ltrApi: {
    listModels: boundary.listModels,
    registerModel: boundary.register,
    activateModel: boundary.activate,
    rollbackActiveModel: boundary.rollback,
  },
}))
vi.mock('@/lib/api/settings', () => ({
  settingsApi: { get: boundary.get, getStatus: boundary.status, update: boundary.update },
}))
vi.mock('@/lib/api/meta', () => ({ metaApi: { details: boundary.meta } }))
vi.mock('@/lib/api/ltr', () => ({
  ltrApi: {
    listModels: boundary.listModels,
    registerModel: boundary.register,
    activateModel: boundary.activate,
    rollbackActiveModel: boundary.rollback,
  },
}))
vi.mock('@/contexts/pipeline-capabilities-context', () => ({
  usePipelineCapabilities: () => ({ refresh: boundary.capabilities }),
}))

import { AUTH_SCOPE_CHANGED_EVENT, setAccessToken, setAuthSession } from '@/lib/auth-storage'
import { useSettingsPageState } from './use-settings-page-state'

const cleanup: Array<() => void> = []
const token = { access_token: 'settings-token', token_type: 'bearer', expires_in: 3600 }
const user = {
  id: 'settings-user',
  username: 'settings',
  email: 'settings@example.com',
  is_active: true,
  created_at: '2026-11-05T00:00:00Z',
}

function settings(topK = 5): SystemSettings {
  return {
    feature_flags: {
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
    },
    kg: {
      chat_enabled: false,
      extract_prompt_template_id: '',
      extract_prompt_template_key: '',
      extract_prompt_ab_experiment_key: '',
      extract_replace_existing: true,
      extract_prune_orphan_entities: true,
    },
    llm: {
      api_key: 'llm***mask',
      api_base: 'https://api.openai.com/v1',
      model: 'gpt-5.4-mini',
      temperature: 0,
      timeout: 60,
      max_retries: 3,
    },
    embedding: {
      api_key: 'embed***mask',
      api_base: 'https://api.openai.com/v1',
      provider: 'openai_compatible',
      model: 'text-embedding-3-small',
    },
    milvus: { host: 'localhost', port: 19530, user: '', password: '', collection_name: 'documents' },
    minio: {
      enabled: false,
      endpoint: 'localhost:9000',
      access_key: 'access***mask',
      secret_key: 'secret***mask',
      bucket_name: 'mimirq',
      use_ssl: false,
      documents_enabled: false,
      image_max_bytes: 0,
    },
    rag: {
      chunk_size: 1000,
      chunk_overlap: 200,
      chunk_min_chars: 0,
      retrieval_top_k: topK,
      similarity_threshold: 0,
      default_parser_backend: 'auto',
      default_chunk_strategy: 'recursive',
      bm25_index_enabled: false,
      enable_reranker: false,
      reranker_provider: 'llm',
      reranker_top_n: 20,
      show_image_in_answer: false,
      image_append_max: 0,
    },
    cache: {
      upload_dedup_enabled: false,
      chat_response_cache_enabled: false,
      chat_response_cache_ttl_sec: 0,
      chat_response_cache_max_value_bytes: 0,
      chat_response_cache_require_empty_history: false,
    },
    url_ingest: { enabled: false, max_bytes: 0, timeout_sec: 0, allow_private_ips: false, follow_redirects: false },
    governance: { enabled: false, pii_anonymize: false, secrets_redact: false, quarantine_on_drop: false },
    mineru: {
      api_token: 'miner***mask',
      api_base: 'https://mineru.net/api/v4',
      model_version: 'vlm',
      backend: 'pipeline',
      local_server_url: '',
      vl_server: '',
    },
    etl4llm: {
      api_url: '',
      timeout_sec: 120,
      mode: 'partition',
      force_ocr: false,
      enable_formula: true,
      extract_images: true,
      filter_page_header_footer: false,
    },
    marker: { api_url: '', timeout_sec: 600 },
    docling: {
      api_url: '',
      api_key: '',
      request_timeout_sec: 600,
      health_timeout_sec: 5,
      http_trust_env: false,
      ocr_enabled: true,
    },
    paddle_vl: { api_url: '', timeout_sec: 600, pipeline_version: 'v1.5', mode: 'doc_parser' },
    textin: {
      api_url: '',
      app_id: '',
      secret_code: 'text***mask',
      timeout_sec: 180,
      parse_mode: 'auto',
      table_flavor: 'html',
      apply_document_tree: true,
      markdown_details: true,
      get_image: 'none',
      dpi: 144,
      page_count: 0,
    },
    magicpdf: {
      api_url: '',
      request_timeout_sec: 600,
      max_concurrent_jobs: 1,
      cli: 'magic-pdf',
      method: 'auto',
      lang: '',
      debug: false,
      timeout_sec: 600,
      models_dir: '',
      device_mode: 'cpu',
      keep_artifacts: false,
    },
    observability: {
      tool_call_log_enabled: false,
      tool_call_log_include_preview: false,
      tool_call_log_max_preview_chars: 0,
      agent_log_enabled: false,
      agent_log_include_execution_path: false,
      agent_log_max_preview_chars: 0,
      metrics_log_enabled: false,
      metrics_log_include_text: false,
    },
    safety: { pii_redaction_enabled: false, pii_redaction_mask: '', pii_stream_holdback_chars: 0 },
    chat: { stream_heartbeat_sec: 0, stream_cancel_on_disconnect: false },
    langgraph: { use_subgraphs: false },
    navigation: { user_visible_modules: [] },
    dify_external_knowledge: {
      enabled: false,
      api_keys: 'dify***mask',
      tenant_id: '',
      account_id: 'system:dify',
      knowledge_map_json: '',
      top_k_max: 50,
      endpoint_path: '/api/v1/integrations/dify/retrieval',
    },
  }
}

function model(id = 'model-a'): LTRModelInfo {
  return {
    model_id: id,
    model_sha256: 'sha',
    size_bytes: 0,
    created_at: '2026-11-05',
    created_by: null,
    feature_spec_version: 1,
    feature_schema: 'features.v1',
    feature_names: ['score'],
    has_manifest: true,
    active: false,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept
    reject = fail
  })
  return { promise, resolve, reject }
}

async function mount() {
  const hook = renderHook(useSettingsPageState)
  cleanup.push(hook.unmount)
  await waitForAssertion(() => expect(hook.result.current.loading).toBe(false))
  return hook
}

beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  setAuthSession({ token, user })
  boundary.get.mockResolvedValue(settings())
  boundary.status.mockResolvedValue(null)
  boundary.meta.mockResolvedValue(null)
  boundary.update.mockResolvedValue({ success: true, message: 'saved', updated_keys: ['RETRIEVAL_TOP_K'] })
  boundary.listModels.mockResolvedValue({ items: [model()], active_model_id: null })
  boundary.register.mockResolvedValue({ success: true })
  boundary.activate.mockResolvedValue({ success: true })
  boundary.rollback.mockResolvedValue({ success: true })
  boundary.capabilities.mockResolvedValue(undefined)
})

afterEach(() => {
  cleanup
    .splice(0)
    .reverse()
    .forEach((dispose) => dispose())
  vi.useRealTimers()
  document.body.replaceChildren()
})

describe('settings read ownership', () => {
  it('retains the latest refresh when an older response finishes last', async () => {
    const hook = await mount()
    const old = deferred<SystemSettings>(),
      current = deferred<SystemSettings>()
    boundary.get.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    act(() => hook.result.current.refreshAll())
    act(() => hook.result.current.refreshAll())
    await act(async () => current.resolve(settings(12)))
    await act(async () => old.resolve(settings(7)))
    expect(hook.result.current.ragMerged.retrieval_top_k).toBe(12)
  })

  it('does not release a newer refresh busy state when an older refresh settles', async () => {
    const hook = await mount()
    const old = deferred<SystemSettings>(),
      current = deferred<SystemSettings>()
    boundary.get.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    act(() => hook.result.current.refreshAll())
    act(() => hook.result.current.refreshAll())
    await act(async () => old.resolve(settings(7)))
    expect(hook.result.current.loading).toBe(true)
    await act(async () => current.resolve(settings(12)))
    expect(hook.result.current.loading).toBe(false)
  })

  it('does not display an old refresh error after a newer success', async () => {
    const hook = await mount()
    const old = deferred<SystemSettings>(),
      current = deferred<SystemSettings>()
    boundary.get.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    act(() => hook.result.current.refreshAll())
    act(() => hook.result.current.refreshAll())
    await act(async () => current.resolve(settings(12)))
    await act(async () => old.reject(new Error('retired load')))
    expect(hook.result.current.loadError).toBeNull()
  })

  it('discards a refresh from an earlier explicit login even when its identity is reused', async () => {
    const hook = await mount(),
      pending = deferred<SystemSettings>()
    boundary.get.mockReturnValueOnce(pending.promise)
    act(() => hook.result.current.refreshAll())
    act(() => setAuthSession({ token, user }))
    await act(async () => pending.resolve(settings(19)))
    expect(hook.result.current.ragMerged.retrieval_top_k).toBe(5)
  })

  it('clears identity-owned drafts and reloads current settings on an auth scope event', async () => {
    const hook = await mount()
    act(() => hook.result.current.updateRag({ retrieval_top_k: 12 }))
    boundary.get.mockResolvedValueOnce(settings(8))
    await act(async () => window.dispatchEvent(new Event(AUTH_SCOPE_CHANGED_EVENT)))
    expect(hook.result.current.ragMerged.retrieval_top_k).toBe(8)
    expect(hook.result.current.hasChanges).toBe(false)
    expect(boundary.get).toHaveBeenCalledTimes(2)
  })

  it('keeps confirmed settings and the actual current load failure', async () => {
    const hook = await mount()
    boundary.get.mockRejectedValueOnce(new Error('current load denied'))
    await act(async () => hook.result.current.refreshAll())
    expect(hook.result.current.loadError).toBe('current load denied')
    expect(hook.result.current.ragMerged.retrieval_top_k).toBe(5)
    expect(hook.result.current.loading).toBe(false)
  })

  it('allows optional status and metadata failure without fabricating a settings failure', async () => {
    boundary.status.mockRejectedValueOnce(new Error('status unavailable'))
    boundary.meta.mockRejectedValueOnce(new Error('meta unavailable'))
    const hook = await mount()
    expect(hook.result.current.ragMerged.retrieval_top_k).toBe(5)
    expect(hook.result.current.status).toBeNull()
    expect(hook.result.current.backendMeta).toBeNull()
    expect(hook.result.current.loadError).toBeNull()
  })
})

describe('settings write and draft ownership', () => {
  it('preserves edits made while a save is pending and only retires its submitted draft', async () => {
    const hook = await mount(),
      pending = deferred<{ updated_keys: string[] }>()
    act(() => hook.result.current.updateRag({ retrieval_top_k: 10 }))
    boundary.update.mockReturnValueOnce(pending.promise)
    boundary.get.mockResolvedValueOnce(settings(10))
    let save!: Promise<void>
    act(() => {
      save = hook.result.current.saveSettings()
    })
    act(() => hook.result.current.updateRag({ retrieval_top_k: 12 }))
    await act(async () => {
      pending.resolve({ updated_keys: ['RETRIEVAL_TOP_K'] })
      await save
    })
    expect(hook.result.current.ragMerged.retrieval_top_k).toBe(12)
    expect(hook.result.current.hasChanges).toBe(true)
    await act(async () => hook.result.current.saveSettings())
    expect(boundary.update.mock.lastCall![0].rag.retrieval_top_k).toBe(12)
  })

  it('keeps unrelated global edits when saving one model provider', async () => {
    const hook = await mount()
    act(() => hook.result.current.updateChat({ stream_heartbeat_sec: 0, stream_cancel_on_disconnect: false }))
    await act(async () =>
      hook.result.current.handleSaveConfig('openai', {
        apiKey: 'new-key',
        apiBase: 'https://api.openai.com/v1',
        model: 'custom',
        temperature: 0,
        timeout: 0,
      }),
    )
    expect(boundary.update).toHaveBeenLastCalledWith({
      llm: {
        api_key: 'new-key',
        api_base: 'https://api.openai.com/v1',
        model: 'custom',
        temperature: 0,
        timeout: 0,
        max_retries: 3,
      },
    })
    expect(hook.result.current.hasChanges).toBe(true)
    expect(hook.result.current.chatMerged.stream_cancel_on_disconnect).toBe(false)
  })

  it('submits only one settings write before React commits its pending state', async () => {
    const hook = await mount(),
      pending = deferred<{ updated_keys: string[] }>()
    act(() => hook.result.current.updateRag({ retrieval_top_k: 10 }))
    boundary.update.mockReturnValue(pending.promise)
    act(() => {
      void hook.result.current.saveSettings()
      void hook.result.current.saveSettings()
    })
    expect(boundary.update).toHaveBeenCalledOnce()
    await act(async () => pending.resolve({ updated_keys: [] }))
  })

  it('does not start a follow-up load or capability refresh after unmounting during save', async () => {
    const hook = await mount(),
      pending = deferred<{ updated_keys: string[] }>()
    act(() => hook.result.current.updateRag({ retrieval_top_k: 10 }))
    boundary.update.mockReturnValueOnce(pending.promise)
    act(() => {
      void hook.result.current.saveSettings()
    })
    hook.unmount()
    cleanup.pop()
    await act(async () => pending.resolve({ updated_keys: [] }))
    expect(boundary.get).toHaveBeenCalledOnce()
    expect(boundary.capabilities).not.toHaveBeenCalled()
  })

  it('retains valid current save completion after normal token rotation', async () => {
    const hook = await mount(),
      pending = deferred<{ updated_keys: string[] }>()
    act(() => hook.result.current.updateRag({ retrieval_top_k: 10 }))
    boundary.update.mockReturnValueOnce(pending.promise)
    act(() => {
      void hook.result.current.saveSettings()
    })
    act(() => setAccessToken({ ...token, access_token: 'rotated' }))
    await act(async () => pending.resolve({ updated_keys: ['RETRIEVAL_TOP_K'] }))
    expect(hook.result.current.saveMessage?.type).toBe('success')
    expect(boundary.capabilities).toHaveBeenCalledOnce()
  })

  it('keeps current edits and the actual backend error after a failed save', async () => {
    const hook = await mount()
    act(() => hook.result.current.updateSafety({ pii_redaction_mask: '', pii_stream_holdback_chars: 0 }))
    boundary.update.mockRejectedValueOnce(new Error('settings write denied'))
    await act(async () => hook.result.current.saveSettings())
    expect(hook.result.current.saveMessage).toMatchObject({ type: 'error', text: 'settings write denied' })
    expect(hook.result.current.hasChanges).toBe(true)
    expect(hook.result.current.safetyMerged).toMatchObject({ pii_redaction_mask: '', pii_stream_holdback_chars: 0 })
  })

  it('retires an old scope save without clearing a current scope save or starting an old follow-up read', async () => {
    const hook = await mount(),
      old = deferred<{ updated_keys: string[] }>(),
      current = deferred<{ updated_keys: string[] }>()
    act(() => hook.result.current.updateRag({ retrieval_top_k: 10 }))
    boundary.update.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    act(() => {
      void hook.result.current.saveSettings()
    })
    await act(async () => window.dispatchEvent(new Event(AUTH_SCOPE_CHANGED_EVENT)))
    act(() => hook.result.current.updateRag({ retrieval_top_k: 12 }))
    act(() => {
      void hook.result.current.saveSettings()
    })
    const readsBeforeOldSettlement = boundary.get.mock.calls.length
    await act(async () => old.resolve({ updated_keys: ['OLD_KEY'] }))
    expect(boundary.get).toHaveBeenCalledTimes(readsBeforeOldSettlement)
    expect(hook.result.current.saving).toBe(true)
    expect(hook.result.current.saveMessage).toBeNull()
    await act(async () => current.resolve({ updated_keys: ['NEW_KEY'] }))
    expect(hook.result.current.lastUpdatedKeys).toEqual(['NEW_KEY'])
  })

  it('does not publish the result or start reads for a save from a replaced login', async () => {
    const hook = await mount(),
      pending = deferred<{ updated_keys: string[] }>()
    act(() => hook.result.current.updateRag({ retrieval_top_k: 10 }))
    boundary.update.mockReturnValueOnce(pending.promise)
    act(() => {
      void hook.result.current.saveSettings()
    })
    act(() => setAuthSession({ token, user }))
    await act(async () => pending.resolve({ updated_keys: ['OLD_KEY'] }))
    expect(boundary.get).toHaveBeenCalledOnce()
    expect(hook.result.current.saveMessage).toBeNull()
    expect(hook.result.current.lastUpdatedKeys).toEqual([])
    expect(hook.result.current.hasChanges).toBe(true)
  })

  it('preserves all section patch semantics including masked secrets, blank paths, false and zero', async () => {
    const hook = await mount()
    act(() => {
      hook.result.current.updateMinIO({ secret_key: '', image_max_bytes: 0, enabled: false })
      hook.result.current.updateMagicPDF({ models_dir: '', keep_artifacts: false })
      hook.result.current.updateDifyExternalKnowledge({ knowledge_map_json: '', api_keys: 'dify***mask' })
    })
    await act(async () => hook.result.current.saveSettings())
    expect(boundary.update.mock.calls[0][0]).toEqual({
      minio: { ...settings().minio, secret_key: '', image_max_bytes: 0, enabled: false },
      magicpdf: { ...settings().magicpdf, models_dir: '', keep_artifacts: false },
      dify_external_knowledge: {
        ...settings().dify_external_knowledge,
        knowledge_map_json: '',
        api_keys: 'dify***mask',
      },
    })
    expect(hook.result.current.hasChanges).toBe(false)
  })

  it('does not let an old five-second feedback timer clear a newer save error', async () => {
    const hook = await mount()
    vi.useFakeTimers()
    act(() => hook.result.current.updateRag({ retrieval_top_k: 10 }))
    await act(async () => hook.result.current.saveSettings())
    act(() => vi.advanceTimersByTime(4000))
    act(() => hook.result.current.updateRag({ retrieval_top_k: 12 }))
    boundary.update.mockRejectedValueOnce(new Error('new save denied'))
    await act(async () => hook.result.current.saveSettings())
    act(() => vi.advanceTimersByTime(1000))
    expect(hook.result.current.saveMessage).toMatchObject({ type: 'error', text: 'new save denied' })
    act(() => vi.advanceTimersByTime(4000))
    expect(hook.result.current.saveMessage).toBeNull()
  })

  it('shows a usable RAG configuration instruction instead of opening an unsupported reranker dialog', async () => {
    const hook = await mount(),
      provider = hook.result.current.groupedProviders.reranker[0]
    act(() => hook.result.current.handleConfigure(provider))
    expect(hook.result.current.dialogOpen).toBe(false)
    expect(hook.result.current.saveMessage).toMatchObject({ type: 'error' })
    expect(hook.result.current.saveMessage?.text).toContain('RAG')
    expect(boundary.update).not.toHaveBeenCalled()
  })

  it('keeps normal model configuration and exact embedding category payloads', async () => {
    const hook = await mount(),
      provider = hook.result.current.groupedProviders.model.find((item) => item.id === 'openai')!
    act(() => hook.result.current.handleConfigure(provider))
    expect(hook.result.current.dialogOpen).toBe(true)
    expect(hook.result.current.selectedProvider).toBe(provider)
    expect(provider.config).toMatchObject({ apiKey: 'llm***mask', model: 'gpt-5.4-mini', temperature: 0 })
    await act(async () =>
      hook.result.current.handleSaveConfig('openai-embedding', {
        apiKey: '',
        apiBase: 'http://models.internal/v1',
        model: 'BAAI/bge-m3',
      }),
    )
    expect(boundary.update).toHaveBeenLastCalledWith({
      embedding: {
        provider: 'openai_compatible',
        model: 'BAAI/bge-m3',
        api_key: '',
        api_base: 'http://models.internal/v1',
      },
    })
  })

  it('keeps API-served BGE models on the configured service instead of inferring local execution', async () => {
    const stored = settings()
    stored.embedding = {
      provider: 'openai_compatible',
      model: 'BAAI/bge-m3',
      api_key: '',
      api_base: 'http://models.internal/v1',
    }
    boundary.get.mockResolvedValue(stored)
    const hook = await mount()
    const provider = hook.result.current.groupedProviders.embedding.find((item) => item.id === 'openai-embedding')
    expect(provider?.config).toMatchObject({ model: 'BAAI/bge-m3', apiBase: 'http://models.internal/v1' })
    expect(hook.result.current.retiredEmbeddingModel).toBeNull()
    expect(boundary.update).not.toHaveBeenCalled()
  })

  it('keeps a saved local model visible for correction without attaching it to a service or writing it', async () => {
    const stored = settings()
    stored.embedding = { provider: 'local', model: 'BAAI/bge-m3', api_key: '', api_base: '' }
    boundary.get.mockResolvedValue(stored)
    const hook = await mount()
    expect(hook.result.current.retiredEmbeddingModel).toBe('BAAI/bge-m3')
    expect(hook.result.current.groupedProviders.embedding.every((item) => !item.isConfigured)).toBe(true)
    expect(boundary.update).not.toHaveBeenCalled()
  })

  it('keeps the Ollama embedding service protocol when displaying and saving its configuration', async () => {
    const stored = settings()
    stored.embedding = {
      provider: 'ollama',
      model: 'nomic-embed-text',
      api_key: '',
      api_base: 'http://localhost:11434',
    }
    boundary.get.mockResolvedValue(stored)
    const hook = await mount()
    const provider = hook.result.current.groupedProviders.embedding.find((item) => item.id === 'ollama-embedding')
    expect(provider?.config).toMatchObject({ model: 'nomic-embed-text', apiBase: 'http://localhost:11434' })
    await act(async () =>
      hook.result.current.handleSaveConfig('ollama-embedding', {
        apiKey: '',
        apiBase: 'http://localhost:11434',
        model: 'nomic-embed-text',
      }),
    )
    expect(boundary.update).toHaveBeenLastCalledWith({ embedding: stored.embedding })
  })

  it('keeps a model dialog closed while another configuration write owns the save lane', async () => {
    const hook = await mount(),
      pending = deferred<{ updated_keys: string[] }>()
    act(() => hook.result.current.updateRag({ retrieval_top_k: 10 }))
    boundary.update.mockReturnValueOnce(pending.promise)
    act(() => {
      void hook.result.current.saveSettings()
    })
    act(() => hook.result.current.handleConfigure(hook.result.current.groupedProviders.model[0]))
    expect(hook.result.current.dialogOpen).toBe(false)
    expect(hook.result.current.saveMessage?.text).toContain('保存')
    await act(async () => pending.resolve({ updated_keys: [] }))
  })
})

describe('LTR reads and writes', () => {
  it('retains the latest list refresh when an earlier read resolves late', async () => {
    const hook = await mount(),
      old = deferred<{ items: LTRModelInfo[] }>(),
      current = deferred<{ items: LTRModelInfo[] }>()
    boundary.listModels.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    act(() => hook.result.current.refreshLtrModels())
    act(() => hook.result.current.refreshLtrModels())
    await act(async () => current.resolve({ items: [model('new')] }))
    await act(async () => old.resolve({ items: [model('old')] }))
    expect(hook.result.current.ltrModels[0].model_id).toBe('new')
  })

  it('starts only one registration for the selected pair before a pending render', async () => {
    const hook = await mount(),
      pending = deferred<unknown>()
    const modelFile = new File(['{}'], 'model.json'),
      manifestFile = new File(['{}'], 'manifest.json')
    act(() => {
      hook.result.current.setLtrUploadModelFile(modelFile)
      hook.result.current.setLtrUploadManifestFile(manifestFile)
    })
    boundary.register.mockReturnValue(pending.promise)
    act(() => {
      void hook.result.current.registerLtrModel()
      void hook.result.current.registerLtrModel()
    })
    expect(boundary.register).toHaveBeenCalledExactlyOnceWith({ modelFile, manifestFile })
    await act(async () => pending.resolve({ success: true }))
  })

  it('does not refresh the registry after its registration owner unmounts', async () => {
    const hook = await mount(),
      pending = deferred<unknown>()
    act(() => {
      hook.result.current.setLtrUploadModelFile(new File(['{}'], 'model.json'))
      hook.result.current.setLtrUploadManifestFile(new File(['{}'], 'manifest.json'))
    })
    boundary.register.mockReturnValueOnce(pending.promise)
    act(() => {
      void hook.result.current.registerLtrModel()
    })
    hook.unmount()
    cleanup.pop()
    await act(async () => pending.resolve({ success: true }))
    expect(boundary.listModels).toHaveBeenCalledOnce()
  })

  it('prevents a second registry mutation before its busy render, then retains the original model ID', async () => {
    const hook = await mount(),
      pending = deferred<unknown>()
    boundary.activate.mockReturnValueOnce(pending.promise)
    act(() => {
      void hook.result.current.activateLtrModel(' model-a ')
      void hook.result.current.rollbackLtrModel()
    })
    expect(boundary.activate).toHaveBeenCalledExactlyOnceWith('model-a')
    expect(boundary.rollback).not.toHaveBeenCalled()
    await act(async () => pending.resolve({ success: true }))
  })

  it('does not publish a registration after a silent session replacement', async () => {
    const hook = await mount(),
      pending = deferred<unknown>()
    act(() => {
      hook.result.current.setLtrUploadModelFile(new File(['{}'], 'model.json'))
      hook.result.current.setLtrUploadManifestFile(new File(['{}'], 'manifest.json'))
    })
    boundary.register.mockReturnValueOnce(pending.promise)
    act(() => {
      void hook.result.current.registerLtrModel()
    })
    act(() => setAuthSession({ token, user }))
    await act(async () => pending.resolve({ success: true }))
    expect(hook.result.current.ltrMessage).toBeNull()
    expect(hook.result.current.ltrUploadReady).toBe(true)
    expect(hook.result.current.ltrUploadResetKey).toBe(0)
  })

  it('retains current registration failure and its selected files without resetting the native inputs', async () => {
    const hook = await mount()
    act(() => {
      hook.result.current.setLtrUploadModelFile(new File(['{}'], 'model.json'))
      hook.result.current.setLtrUploadManifestFile(new File(['{}'], 'manifest.json'))
    })
    boundary.register.mockRejectedValueOnce(new Error('manifest validation failed'))
    await act(async () => hook.result.current.registerLtrModel())
    expect(hook.result.current.ltrMessage).toEqual({ type: 'error', text: 'manifest validation failed' })
    expect(hook.result.current.ltrUploadReady).toBe(true)
    expect(hook.result.current.ltrUploadResetKey).toBe(0)
    expect(boundary.listModels).toHaveBeenCalledOnce()
  })

  it('clears the successfully registered pair through the existing reset key and refreshes its list', async () => {
    const hook = await mount()
    act(() => {
      hook.result.current.setLtrUploadModelFile(new File(['{}'], 'model.json'))
      hook.result.current.setLtrUploadManifestFile(new File(['{}'], 'manifest.json'))
    })
    await act(async () => hook.result.current.registerLtrModel())
    expect(hook.result.current.ltrMessage).toMatchObject({ type: 'success' })
    expect(hook.result.current.ltrUploadReady).toBe(false)
    expect(hook.result.current.ltrUploadResetKey).toBe(1)
    expect(boundary.listModels).toHaveBeenCalledTimes(2)
  })

  it('retains the current activation permission failure and releases its original busy flag', async () => {
    const hook = await mount()
    boundary.activate.mockRejectedValueOnce(new Error('LTR write denied'))
    await act(async () => hook.result.current.activateLtrModel('model-a'))
    expect(hook.result.current.ltrMessage).toEqual({ type: 'error', text: 'LTR write denied' })
    expect(hook.result.current.ltrBusyModelId).toBeNull()
    expect(boundary.listModels).toHaveBeenCalledOnce()
  })
})
