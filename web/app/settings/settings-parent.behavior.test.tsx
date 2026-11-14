// @vitest-environment happy-dom

import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitForAssertion } from '@/test/hook-harness'
import type { SystemSettings } from '@/types/settings'
import { AUTH_SCOPE_CHANGED_EVENT, setAccessToken } from '@/lib/auth-storage'
import { cleanupAdmin, deferred, login } from './access-admin-test-harness'
import { useSettingsPageState } from './use-settings-page-state'

const boundary = vi.hoisted(() => ({
  get: vi.fn(),
  status: vi.fn(),
  meta: vi.fn(),
  update: vi.fn(),
  capabilities: vi.fn(),
}))
vi.mock('@/lib/api/settings', () => ({
  settingsApi: { get: boundary.get, getStatus: boundary.status, update: boundary.update },
}))
vi.mock('@/lib/api/meta', () => ({ metaApi: { details: boundary.meta } }))
vi.mock('@/contexts/pipeline-capabilities-context', () => ({
  usePipelineCapabilities: () => ({ refresh: boundary.capabilities }),
}))

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
    url_ingest: { enabled: false },
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

let stored: SystemSettings
const cleanup: Array<() => void> = []
const success = { success: true, message: 'saved', updated_keys: [] }
function persist(patch: Partial<SystemSettings>) {
  stored = { ...stored, ...structuredClone(patch) }
  return success
}
async function mount() {
  const hook = renderHook(useSettingsPageState)
  cleanup.push(hook.unmount)
  await waitForAssertion(() => expect(hook.result.current.loading).toBe(false))
  return hook
}
const changeScope = () => act(() => window.dispatchEvent(new Event(AUTH_SCOPE_CHANGED_EVENT)))
beforeEach(() => {
  vi.resetAllMocks()
  login()
  stored = settings()
  boundary.get.mockImplementation(async () => structuredClone(stored))
  boundary.update.mockImplementation(async (patch) => persist(patch))
  boundary.status.mockResolvedValue(null)
  boundary.meta.mockResolvedValue(null)
  boundary.capabilities.mockResolvedValue(undefined)
})
afterEach(async () => {
  for (const dispose of cleanup.splice(0).reverse()) dispose()
  await act(async () => {})
  vi.useRealTimers()
  cleanupAdmin()
})

describe('automatic settings read ownership', () => {
  it.each(['late success', 'late failure'] as const)('keeps the latest scope read after %s', async (kind) => {
    const hook = await mount(),
      old = deferred<SystemSettings>(),
      current = deferred<SystemSettings>()
    boundary.get.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    changeScope()
    changeScope()
    await act(async () => current.resolve(settings(9)))
    expect(hook.result.current.ragMerged.retrieval_top_k).toBe(9)
    await act(async () => (kind === 'late success' ? old.resolve(settings(2)) : old.reject(new Error('old read'))))
    expect(hook.result.current.ragMerged.retrieval_top_k).toBe(9)
    expect(hook.result.current.loadError).toBeNull()
  })
  it('does not release a newer read busy state when an old read settles', async () => {
    const hook = await mount(),
      old = deferred<SystemSettings>(),
      current = deferred<SystemSettings>()
    boundary.get.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    changeScope()
    changeScope()
    await act(async () => old.resolve(settings(2)))
    expect(hook.result.current.loading).toBe(true)
    await act(async () => current.resolve(settings(9)))
    expect(hook.result.current.loading).toBe(false)
  })
  it('clears private drafts and reloads settings when the authentication scope changes', async () => {
    const hook = await mount(),
      pending = deferred<SystemSettings>()
    act(() => hook.result.current.updateRag({ retrieval_top_k: 11 }))
    boundary.get.mockReturnValueOnce(pending.promise)
    act(() => login('replacement'))
    expect(hook.result.current.hasChanges).toBe(false)
    expect(hook.result.current.loading).toBe(true)
    await act(async () => pending.resolve(settings(7)))
    expect(hook.result.current.ragMerged.retrieval_top_k).toBe(7)
    expect(boundary.update).not.toHaveBeenCalled()
  })
  it('shows the current settings error and tolerates optional status/metadata failures', async () => {
    boundary.get.mockRejectedValueOnce(new Error('settings unavailable'))
    const hook = await mount()
    expect(hook.result.current.loadError).toContain('settings unavailable')
    boundary.status.mockRejectedValue(new Error('status unavailable'))
    boundary.meta.mockRejectedValue(new Error('metadata unavailable'))
    changeScope()
    await waitForAssertion(() => expect(hook.result.current.loading).toBe(false))
    expect(hook.result.current.loadError).toBeNull()
    expect(hook.result.current.ragMerged.retrieval_top_k).toBe(5)
    expect(hook.result.current.status).toBeNull()
  })
})

describe('automatic settings writes and retained drafts', () => {
  it('serializes synchronous requests and retains newer submitted-section edits', async () => {
    const hook = await mount(),
      pending = deferred<typeof success>()
    boundary.update.mockReturnValueOnce(pending.promise)
    act(() => {
      hook.result.current.updateGovernance({ enabled: true })
      hook.result.current.updateGovernance({ pii_anonymize: true })
      void hook.result.current.retrySave()
      void hook.result.current.retrySave()
    })
    expect(boundary.update).toHaveBeenCalledOnce()
    expect(hook.result.current.governanceMerged).toMatchObject({ enabled: true, pii_anonymize: true })
    await act(async () => {
      persist({ governance: { ...stored.governance, enabled: true } })
      pending.resolve(success)
    })
    expect(boundary.update).toHaveBeenCalledTimes(2)
    expect(stored.governance).toMatchObject({ enabled: true, pii_anonymize: true })
    expect(hook.result.current.hasChanges).toBe(false)
  })
  it('preserves an unrelated debounced draft when saving one model provider', async () => {
    const hook = await mount()
    act(() => hook.result.current.updateRag({ retrieval_top_k: 12 }))
    await act(async () =>
      hook.result.current.handleSaveConfig('openai', {
        apiKey: '',
        apiBase: '',
        model: 'next',
        temperature: 0,
        timeout: 60,
      }),
    )
    expect(boundary.update).toHaveBeenCalledExactlyOnceWith({
      llm: { api_key: '', api_base: '', model: 'next', temperature: 0, timeout: 60, max_retries: 3 },
    })
    expect(hook.result.current.ragMerged.retrieval_top_k).toBe(12)
    expect(hook.result.current.hasChanges).toBe(true)
    await act(async () => hook.result.current.retrySave())
    expect(stored.rag.retrieval_top_k).toBe(12)
  })
  it('does not start follow-up reads or capability refresh after unmount', async () => {
    const hook = await mount(),
      pending = deferred<typeof success>()
    boundary.update.mockReturnValueOnce(pending.promise)
    act(() => hook.result.current.updateGovernance({ enabled: true }))
    hook.unmount()
    const reads = boundary.get.mock.calls.length
    await act(async () => pending.resolve(success))
    expect(boundary.get).toHaveBeenCalledTimes(reads)
    expect(boundary.capabilities).not.toHaveBeenCalled()
  })
  it('allows current completion after ordinary access-token rotation', async () => {
    const hook = await mount(),
      pending = deferred<typeof success>()
    boundary.update.mockReturnValueOnce(pending.promise)
    act(() => hook.result.current.updateGovernance({ enabled: true }))
    act(() => setAccessToken({ access_token: 'rotated', token_type: 'bearer', expires_in: 3600 }))
    await act(async () => {
      persist({ governance: { ...stored.governance, enabled: true } })
      pending.resolve(success)
    })
    expect(hook.result.current.governanceMerged.enabled).toBe(true)
    expect(hook.result.current.hasChanges).toBe(false)
    expect(hook.result.current.saveError).toBeNull()
  })
  it('keeps failed input and actual errors until a successful explicit retry', async () => {
    const hook = await mount()
    boundary.update.mockRejectedValueOnce(new Error('write conflict'))
    await act(async () => hook.result.current.updateGovernance({ enabled: true }))
    expect(hook.result.current.hasChanges).toBe(true)
    expect(hook.result.current.saveError).toContain('write conflict')
    await act(async () => hook.result.current.retrySave())
    expect(stored.governance.enabled).toBe(true)
    expect(hook.result.current.hasChanges).toBe(false)
  })
  it('does not let an old scope completion release or reload a newer scope save', async () => {
    const hook = await mount(),
      old = deferred<typeof success>(),
      current = deferred<typeof success>()
    boundary.update.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    act(() => hook.result.current.updateGovernance({ enabled: true }))
    act(() => login('replacement'))
    await waitForAssertion(() => expect(hook.result.current.loading).toBe(false))
    act(() => hook.result.current.updateGovernance({ pii_anonymize: true }))
    const reads = boundary.get.mock.calls.length
    await act(async () => old.resolve(success))
    expect(hook.result.current.saving).toBe(true)
    expect(boundary.get).toHaveBeenCalledTimes(reads)
    expect(boundary.capabilities).not.toHaveBeenCalled()
    await act(async () => {
      persist({ governance: { ...stored.governance, pii_anonymize: true } })
      current.resolve(success)
    })
    expect(hook.result.current.governanceMerged).toMatchObject({ enabled: false, pii_anonymize: true })
    expect(hook.result.current.saving).toBe(false)
  })
  it('keeps a newer failure visible beyond the former success-message timeout', async () => {
    const hook = await mount()
    vi.useFakeTimers()
    await act(async () => hook.result.current.updateGovernance({ enabled: true }))
    boundary.update.mockRejectedValueOnce(new Error('new failure'))
    await act(async () => hook.result.current.updateGovernance({ enabled: false }))
    await act(async () => vi.advanceTimersByTimeAsync(6000))
    expect(hook.result.current.saveError).toContain('new failure')
    expect(hook.result.current.hasChanges).toBe(true)
  })
  it('preserves secret, blank-path, false and zero patch semantics', async () => {
    const hook = await mount()
    act(() => {
      hook.result.current.updateMinerU({ api_token: '', local_server_url: '' })
      hook.result.current.updateTextIn({ secret_code: '' })
      hook.result.current.updateMagicPDF({ models_dir: '' })
      hook.result.current.updateRag({ chunk_min_chars: 0, show_image_in_answer: false })
    })
    await act(async () => hook.result.current.retrySave())
    expect(stored.mineru).toMatchObject({ api_token: '', local_server_url: '' })
    expect(stored.textin.secret_code).toBe('')
    expect(stored.magicpdf.models_dir).toBe('')
    expect(stored.rag).toMatchObject({ chunk_min_chars: 0, show_image_in_answer: false })
  })
})

describe('model configuration', () => {
  it('points reranker configuration to the actual retrieval settings', async () => {
    const hook = await mount()
    act(() => hook.result.current.handleConfigure(hook.result.current.groupedProviders.reranker[0]))
    expect(hook.result.current.dialogOpen).toBe(false)
    expect(hook.result.current.saveError).toContain('检索与生成')
    expect(boundary.update).not.toHaveBeenCalled()
  })
  it('keeps the normal model dialog closed while another write owns saving', async () => {
    const hook = await mount(),
      pending = deferred<typeof success>()
    boundary.update.mockReturnValueOnce(pending.promise)
    act(() => hook.result.current.updateGovernance({ enabled: true }))
    act(() => hook.result.current.handleConfigure(hook.result.current.groupedProviders.model[0]))
    expect(hook.result.current.dialogOpen).toBe(false)
    expect(hook.result.current.saveError).toContain('保存')
    await act(async () => pending.resolve(success))
  })
  it('saves a complete embedding form once with exact category payloads', async () => {
    const hook = await mount(),
      pending = deferred<typeof success>()
    boundary.update.mockReturnValueOnce(pending.promise)
    act(() => {
      void hook.result.current.handleSaveConfig('openai-embedding', {
        apiKey: '',
        apiBase: 'http://models.internal/v1',
        model: 'BAAI/bge-m3',
      })
      void hook.result.current.handleSaveConfig('openai-embedding', {
        apiKey: '',
        apiBase: 'http://models.internal/v1',
        model: 'BAAI/bge-m3',
      })
    })
    expect(boundary.update).toHaveBeenCalledExactlyOnceWith({
      embedding: {
        provider: 'openai_compatible',
        model: 'BAAI/bge-m3',
        api_key: '',
        api_base: 'http://models.internal/v1',
      },
    })
    await act(async () => pending.resolve(success))
  })
  it.each([
    ['openai_compatible', 'BAAI/bge-m3', 'http://models.internal/v1', 'openai-embedding'],
    ['ollama', 'nomic-embed-text', 'http://localhost:11434', 'ollama-embedding'],
  ])('displays %s embedding as the saved service protocol', async (provider, model, api_base, id) => {
    stored.embedding = { provider, model, api_key: '', api_base }
    const hook = await mount()
    expect(hook.result.current.groupedProviders.embedding.find((item) => item.id === id)?.config).toMatchObject({
      model,
      apiBase: api_base,
    })
    expect(hook.result.current.retiredEmbeddingModel).toBeNull()
    expect(boundary.update).not.toHaveBeenCalled()
  })
  it('keeps a retired local embedding visible without inferring a serving endpoint', async () => {
    stored.embedding = { provider: 'local', model: 'BAAI/bge-m3', api_key: '', api_base: '' }
    const hook = await mount()
    expect(hook.result.current.retiredEmbeddingModel).toBe('BAAI/bge-m3')
    expect(hook.result.current.groupedProviders.embedding.every((item) => !item.isConfigured)).toBe(true)
    expect(boundary.update).not.toHaveBeenCalled()
  })
})
