// @vitest-environment happy-dom
import React, { act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Dataset, SystemSettings } from '@/types'

const ports = vi.hoisted(() => ({
  datasets: { update: vi.fn(), get: vi.fn() },
  settings: { get: vi.fn(), update: vi.fn() },
  retrieval: { configHash: vi.fn() },
  translate: (key: string) => key,
  toast: { success: vi.fn(), error: vi.fn() },
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api', () => ({ datasetApi: ports.datasets, settingsApi: ports.settings, retrievalApi: ports.retrieval }))
vi.mock('@/lib/api/datasets', () => ({ datasetApi: ports.datasets }))
vi.mock('@/lib/api/settings', () => ({ settingsApi: ports.settings }))
vi.mock('@/lib/api/rag', () => ({ retrievalApi: ports.retrieval }))
vi.mock('next-intl', () => ({ useTranslations: () => ports.translate }))
vi.mock('sonner', () => ({ toast: ports.toast }))
// Native select adapter preserves the production controlled value/change/disabled contract.
vi.mock('@/components/ui/select', async () => {
  const React = await import('react')
  return {
    Select: ({
      value,
      onValueChange,
      disabled,
      children,
    }: {
      value: string
      onValueChange?: (value: string) => void
      disabled?: boolean
      children?: React.ReactNode
    }) => (
      <select value={value} onChange={(event) => onValueChange?.(event.target.value)} disabled={disabled}>
        {children}
      </select>
    ),
    SelectTrigger: () => null,
    SelectValue: () => null,
    SelectContent: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
    SelectItem: ({ value, children }: { value: string; children?: React.ReactNode }) => (
      <option value={value}>{children}</option>
    ),
  }
})

import { KnowledgeSettingsPanel } from './knowledge-settings-panel'
import { clearAuthSession, setAuthSession } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'

// Complete frozen SystemSettings fixture reused from the existing settings parent suite.
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

const cleanup: Array<() => void> = []
const datasets: Dataset[] = [
  {
    id: 'dataset-a',
    tenant_id: 'tenant-a',
    name: 'Dataset A',
    permission: 'only_me',
    embedding_defaults: {
      provider: 'openai_compatible',
      model: 'text-embedding-3-small',
      api_base: 'https://api.openai.com/v1',
    },
    rag_defaults: { top_k: 5, score_threshold: 0.7, retrieval_mode: 'hybrid' },
  },
  {
    id: 'dataset-b',
    tenant_id: 'tenant-a',
    name: 'Dataset B',
    permission: 'only_me',
    embedding_defaults: {
      provider: 'dashscope',
      model: 'text-embedding-v4',
      api_base: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    },
    rag_defaults: { top_k: 21, score_threshold: 0.4, retrieval_mode: 'vector' },
  },
]
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
function session() {
  setAuthSession({
    user: {
      id: 'review-user',
      username: 'review-user',
      email: 'review@example.test',
      is_active: true,
      created_at: '',
      last_login_at: null,
    },
    token: { access_token: 'review-token', token_type: 'bearer', expires_in: 3600 },
  })
}
async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const holder = document.createElement('div')
  document.body.appendChild(holder)
  const root = createRoot(holder)
  function Harness() {
    const [id, setId] = useState('dataset-a')
    return (
      <KnowledgeSettingsPanel
        selectedDatasetId={id}
        selectedDataset={datasets.find((dataset) => dataset.id === id)}
        datasets={datasets}
        onDatasetScopeChange={setId}
      />
    )
  }
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <Harness />
      </QueryClientProvider>,
    ),
  )
  await act(async () => {})
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
  cleanup.push(() => {
    act(() => root.unmount())
    client.clear()
    holder.remove()
  })
  return { holder, client }
}
function button(text: string) {
  const value = Array.from(document.body.querySelectorAll<HTMLButtonElement>('button')).find(
    (element) => element.textContent?.trim() === text,
  )
  expect(value, text).toBeDefined()
  return value!
}
function click(text: string) {
  act(() => button(text).click())
}
function switchScope(value: string) {
  const select = Array.from(document.body.querySelectorAll<HTMLSelectElement>('select')).find((element) =>
    element.value.startsWith('dataset-'),
  )!
  expect(select.disabled).toBe(false)
  act(() => {
    select.value = value
    select.dispatchEvent(new Event('change', { bubbles: true }))
  })
}
function topK() {
  return document.body.querySelector<HTMLInputElement>('input[type="range"][max="50"]')!
}
function editTopK(value: number) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(topK(), String(value))
    topK().dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  clearAuthSession()
  session()
  ports.settings.get.mockReset().mockResolvedValue(settings())
  ports.settings.update.mockReset().mockResolvedValue({ success: true })
  ports.datasets.update.mockReset().mockResolvedValue(undefined)
  ports.datasets.get.mockReset().mockImplementation(async (id: string) => ({
    ...datasets.find((dataset) => dataset.id === id),
    rag_defaults: { top_k: 12, score_threshold: 0.6, retrieval_mode: 'hybrid' },
  }))
  ports.retrieval.configHash.mockReset().mockResolvedValue({ hash: 'verified-hash', effective_config: { top_k: 12 } })
})
afterEach(() => {
  for (const dispose of cleanup.splice(0)) dispose()
})

describe('knowledge settings save ownership', () => {
  it('keeps the selected B draft when an accepted A save finishes later', async () => {
    const response = deferred<unknown>()
    ports.datasets.update.mockReturnValueOnce(response.promise)
    const view = await mount()
    click('应用建议值')
    click('保存配置')
    switchScope('dataset-b')
    expect(topK().value).toBe('21')
    await act(async () => response.resolve(undefined))
    expect(topK().value).toBe('21')
    expect(document.body.querySelector('button[aria-pressed="true"]')?.textContent).toContain('text-embedding-v4')
    expect(view.client.getQueryData<Dataset>(queryKeys.datasets.detail('dataset-a'))?.id).toBe('dataset-a')
  })

  it('keeps a newer draft after A to B to A revisits while the first A save is pending', async () => {
    const response = deferred<unknown>()
    ports.datasets.update.mockReturnValueOnce(response.promise)
    await mount()
    click('应用建议值')
    click('保存配置')
    switchScope('dataset-b')
    switchScope('dataset-a')
    editTopK(18)
    expect(topK().value).toBe('18')
    await act(async () => response.resolve(undefined))
    expect(topK().value).toBe('18')
  })

  it('does not issue old-session rereads or cache writes after the login was explicitly replaced', async () => {
    const response = deferred<unknown>()
    ports.datasets.update.mockReturnValueOnce(response.promise)
    const view = await mount()
    click('应用建议值')
    click('保存配置')
    act(() => session())
    await act(async () => response.resolve(undefined))
    expect(ports.datasets.get).not.toHaveBeenCalled()
    expect(view.client.getQueryData(queryKeys.datasets.detail('dataset-a'))).toBeUndefined()
    expect(ports.toast.success).toHaveBeenCalledTimes(1) // The initial apply-to-draft notice only.
    expect(button('保存配置').disabled).toBe(false)
  })

  it('accepts only one save from two synchronous clicks', async () => {
    const response = deferred<unknown>()
    ports.datasets.update.mockReturnValue(response.promise)
    await mount()
    click('应用建议值')
    const save = button('保存配置')
    act(() => {
      save.click()
      save.click()
    })
    expect(ports.datasets.update).toHaveBeenCalledOnce()
    await act(async () => response.resolve(undefined))
  })

  it('saves, rereads, caches and verifies the current dataset snapshot', async () => {
    const view = await mount()
    click('应用建议值')
    click('保存配置')
    await act(async () => {})
    expect(ports.datasets.update).toHaveBeenCalledWith('dataset-a', {
      embedding_defaults: {
        provider: 'openai_compatible',
        model: 'text-embedding-3-small',
        api_base: 'https://api.openai.com/v1',
      },
      rag_defaults: { top_k: 12, score_threshold: 0.6, retrieval_mode: 'hybrid' },
    })
    expect(view.client.getQueryData<Dataset>(queryKeys.datasets.detail('dataset-a'))?.rag_defaults?.top_k).toBe(12)
    expect(ports.retrieval.configHash).toHaveBeenCalledWith({
      rag_config: { top_k: 12, score_threshold: 0.6, retrieval_mode: 'hybrid' },
      include_runtime_defaults: true,
    })
    expect(topK().value).toBe('12')
    expect(button('保存配置').disabled).toBe(true)
    expect(document.body.textContent).toContain('已同步')
  })

  it('keeps the current draft editable when its save fails', async () => {
    ports.datasets.update.mockRejectedValueOnce(new Error('current save rejected'))
    await mount()
    click('应用建议值')
    click('保存配置')
    await act(async () => {})
    expect(topK().value).toBe('12')
    expect(button('保存配置').disabled).toBe(false)
    expect(ports.toast.error).toHaveBeenCalledWith('current save rejected')
    expect(ports.datasets.get).not.toHaveBeenCalled()
  })
})
