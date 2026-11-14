// @vitest-environment happy-dom

import React, { act, useState, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Dataset } from '@/types/datasets'
import { waitForAssertion } from '@/test/hook-harness'

const boundary = vi.hoisted(() => ({ listAll: vi.fn(), copy: vi.fn(), toastError: vi.fn() }))
vi.mock('@/lib/api', () => ({ datasetApi: { listAll: boundary.listAll } }))
vi.mock('@/lib/api/datasets', () => ({ datasetApi: { listAll: boundary.listAll } }))
vi.mock('sonner', () => ({ toast: { error: boundary.toastError } }))

import { DifyIntegrationSection } from './dify-integration-section'
import { ParserServicesSection } from './parser-services-section'

type DifyConfig = React.ComponentProps<typeof DifyIntegrationSection>['difyExternalKnowledge']
type ParserProps = React.ComponentProps<typeof ParserServicesSection>

const cleanup: Array<() => void> = []
const originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
const DATASET: Dataset = { id: 'dataset-a', name: '资料 A', tenant_id: 'tenant-a', permission: 'only_me' }
const ADVANCED_BINDING = {
  dataset_ids: ['dataset-old'],
  query_routes: [{ terms: ['policy'], dataset_ids: ['dataset-route'], mode: 'replace' }],
  strict_query_routes: true,
  inherit_query_routes_from: ['shared-routes'],
  plugin_refs: ['policy-scope'],
}

function difyConfig(extra: Partial<DifyConfig> = {}): DifyConfig {
  return {
    enabled: false,
    api_keys: 'dify***mask',
    tenant_id: 'tenant-a',
    account_id: 'system:dify',
    knowledge_map_json: '',
    top_k_max: 50,
    endpoint_path: '/api/v1/integrations/dify/retrieval',
    ...extra,
  }
}

function parserProps(): ParserProps {
  return {
    mineru: {
      api_token: 'token***mask',
      api_base: 'https://mineru.net/api/v4',
      backend: 'pipeline',
      model_version: 'vlm',
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
      api_key: 'docling***mask',
      request_timeout_sec: 600,
      health_timeout_sec: 5,
      http_trust_env: false,
      ocr_enabled: true,
    },
    paddleVl: { api_url: '', timeout_sec: 600, pipeline_version: 'v1.5', mode: 'doc_parser' },
    textIn: {
      api_url: 'https://api.textin.com/ai/service/v1/pdf_to_markdown',
      app_id: '',
      secret_code: 'textin***mask',
      timeout_sec: 180,
      parse_mode: 'auto',
      table_flavor: 'html',
      apply_document_tree: true,
      markdown_details: true,
      get_image: 'none',
      dpi: 144,
      page_count: 0,
    },
    magicPdf: {
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
    updateMinerU: vi.fn(),
    updateEtl4Llm: vi.fn(),
    updateMarker: vi.fn(),
    updateDocling: vi.fn(),
    updatePaddleVL: vi.fn(),
    updateTextIn: vi.fn(),
    updateMagicPDF: vi.fn(),
  }
}

function mount(children: ReactNode) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  let mounted = true
  act(() => root.render(children))
  const unmount = () => {
    if (!mounted) return
    mounted = false
    act(() => root.unmount())
    container.remove()
  }
  cleanup.push(unmount)
  return { container, unmount }
}

function mountControlled<T extends object>(
  initial: T,
  render: (value: T, update: (patch: Partial<T>) => void) => ReactNode,
) {
  const onPatch = vi.fn<(patch: Partial<T>) => void>()
  function Harness() {
    const [value, setValue] = useState(initial)
    return render(value, (patch) => {
      onPatch(patch)
      setValue((previous) => ({ ...previous, ...patch }))
    })
  }
  return { ...mount(<Harness />), onPatch }
}

async function mountDify(extra: Partial<DifyConfig> = {}) {
  const view = mountControlled(difyConfig(extra), (value, update) => (
    <DifyIntegrationSection difyExternalKnowledge={value} updateDifyExternalKnowledge={update} />
  ))
  await act(async () => {})
  return view
}

function button(scope: ParentNode, text: string) {
  const match = [...scope.querySelectorAll<HTMLButtonElement>('button')].find(
    (item) => item.getAttribute('aria-label') === text || item.textContent?.trim() === text,
  )
  expect(match, `button ${text}`).toBeDefined()
  return match!
}

function input(scope: ParentNode, label: string) {
  const field = [...scope.querySelectorAll('div,span,label')].find(
    (item) => item.textContent?.trim() === label && item.parentElement?.querySelector('input'),
  )
  const target = field?.querySelector('input') ?? field?.parentElement?.querySelector('input')
  expect(target, `input ${label}`).toBeDefined()
  return target!
}

function fill(target: HTMLInputElement, value: string, numericValue?: number) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(target, value)
    if (numericValue !== undefined) {
      expect(target.valueAsNumber).toBe(numericValue)
    }
    target.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

async function generateBinding(view: Awaited<ReturnType<typeof mountDify>>, knowledgeId: string) {
  await waitForAssertion(() => expect(view.container.textContent).toContain('资料 A'))
  act(() => button(view.container, '资料 A').click())
  fill(view.container.querySelector<HTMLInputElement>('input[placeholder="knowledge_id"]')!, knowledgeId)
  act(() => button(view.container, '生成绑定').click())
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
  boundary.listAll.mockResolvedValue([DATASET])
  boundary.copy.mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: boundary.copy } })
})

afterEach(() => {
  for (const dispose of cleanup.splice(0).reverse()) dispose()
  if (originalClipboard) Object.defineProperty(navigator, 'clipboard', originalClipboard)
  else Reflect.deleteProperty(navigator, 'clipboard')
  document.body.innerHTML = ''
})

describe('Dify binding preservation', () => {
  it('keeps existing advanced mappings when generating an unrelated binding', async () => {
    const view = await mountDify({
      knowledge_map_json: JSON.stringify({ existing: ADVANCED_BINDING, legacy: 'dataset-legacy' }),
    })
    await generateBinding(view, 'new-binding')

    expect(JSON.parse(view.onPatch.mock.lastCall![0].knowledge_map_json!)).toEqual({
      existing: ADVANCED_BINDING,
      legacy: 'dataset-legacy',
      'new-binding': ['dataset-a'],
    })
    expect(view.onPatch.mock.lastCall![0]).not.toHaveProperty('api_keys')
  })

  it.each(['dataset_ids', 'datasets', 'dataset_id'] as const)(
    'keeps advanced options when replacing the %s selection of one binding',
    async (selector) => {
      const existing = { ...ADVANCED_BINDING, [selector]: selector === 'dataset_id' ? 'dataset-old' : ['dataset-old'] }
      if (selector !== 'dataset_ids') Reflect.deleteProperty(existing, 'dataset_ids')
      const view = await mountDify({ knowledge_map_json: JSON.stringify({ existing }) })
      await generateBinding(view, 'existing')

      expect(JSON.parse(view.onPatch.mock.lastCall![0].knowledge_map_json!)).toEqual({
        existing: { ...existing, [selector]: ['dataset-a'] },
      })
    },
  )

  it('only removes the selected binding and leaves every other raw JSON value intact', async () => {
    const view = await mountDify({
      knowledge_map_json: JSON.stringify({
        keep: ADVANCED_BINDING,
        remove: ['dataset-remove'],
        unknown: { future_option: true },
      }),
    })
    act(() => button(view.container, '删除 remove 绑定').click())

    expect(JSON.parse(view.onPatch.mock.lastCall![0].knowledge_map_json!)).toEqual({
      keep: ADVANCED_BINDING,
      unknown: { future_option: true },
    })
  })

  it('keeps the empty-string setting when the last binding is removed', async () => {
    const view = await mountDify({ knowledge_map_json: '{"only":["dataset-a"]}' })
    act(() => button(view.container, '删除 only 绑定').click())
    expect(view.onPatch).toHaveBeenCalledWith({ knowledge_map_json: '' })
  })

  it('shows invalid JSON object shape instead of silently presenting an empty map', async () => {
    const view = await mountDify({ knowledge_map_json: '[]' })
    expect(view.container.textContent).toContain('JSON')
    expect(view.container.textContent).toContain('重新生成')
  })

  it('shows a failed dataset load and leaves binding generation unavailable', async () => {
    boundary.listAll.mockRejectedValue(new Error('datasets unavailable'))
    const view = await mountDify()
    await waitForAssertion(() => expect(view.container.textContent).toContain('数据集加载失败'))
    expect(button(view.container, '生成绑定').disabled).toBe(true)
  })
})

describe('Dify clipboard boundary', () => {
  it('reports clipboard rejection instead of leaving an unhandled event promise', async () => {
    boundary.copy.mockRejectedValue(new Error('clipboard denied'))
    const view = await mountDify()
    act(() => button(view.container, '复制检索地址').click())
    await waitForAssertion(() => expect(boundary.toastError).toHaveBeenCalledOnce())
    expect(boundary.copy).toHaveBeenCalledWith(`${window.location.origin}/api/v1/integrations/dify/retrieval`)
  })

  it('reports a missing clipboard capability', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
    const view = await mountDify()
    act(() => button(view.container, '复制检索地址').click())
    await waitForAssertion(() => expect(boundary.toastError).toHaveBeenCalledOnce())
  })

  it('does not publish a late clipboard error after leaving the section', async () => {
    let rejectCopy!: (error: Error) => void
    boundary.copy.mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          rejectCopy = reject
        }),
    )
    const view = await mountDify()
    act(() => button(view.container, '复制检索地址').click())
    view.unmount()

    await act(async () => rejectCopy(new Error('late clipboard error')))

    expect(boundary.toastError).not.toHaveBeenCalled()
  })
})

describe('native numeric input values', () => {
  it('keeps a fractional integer setting available for server validation', async () => {
    const view = await mountDify()
    fill(input(view.container, '最大返回条数'), '1.5', 1.5)
    expect(view.onPatch).toHaveBeenLastCalledWith({ top_k_max: 1.5 })
    expect(input(view.container, '最大返回条数').validity.stepMismatch).toBe(true)
  })
  it('passes a full numeric exponent to Dify top_k_max', async () => {
    const view = await mountDify()
    fill(input(view.container, '最大返回条数'), '1e2', 100)
    expect(view.onPatch).toHaveBeenLastCalledWith({ top_k_max: 100 })
  })

  it.each([
    ['ETL4LLM 配置', '超时（秒）', 'updateEtl4Llm', 'timeout_sec'],
    ['Docling Serve 配置', '转换超时（秒）', 'updateDocling', 'request_timeout_sec'],
    ['Docling Serve 配置', '健康检查超时（秒）', 'updateDocling', 'health_timeout_sec'],
    ['Marker 配置', '超时（秒）', 'updateMarker', 'timeout_sec'],
    ['PaddleOCR-VL 配置', '超时（秒）', 'updatePaddleVL', 'timeout_sec'],
    ['TextIn xParse 配置', '超时（秒）', 'updateTextIn', 'timeout_sec'],
    ['TextIn xParse 配置', 'DPI', 'updateTextIn', 'dpi'],
    ['TextIn xParse 配置', '页数限制（0=全部）', 'updateTextIn', 'page_count'],
    ['MagicPDF 配置', '超时（秒）', 'updateMagicPDF', 'timeout_sec'],
  ] as const)('passes the full exponent to %s / %s', (title, label, callback, key) => {
    const props = parserProps()
    const view = mount(<ParserServicesSection {...props} />)
    const section = [...view.container.querySelectorAll('section')].find(
      (node) => node.querySelector('h2')?.textContent?.trim() === title,
    )!
    fill(input(section, label), '1e2', 100)
    expect(props[callback]).toHaveBeenLastCalledWith({ [key]: 100 })
  })

  it('keeps existing parser blank defaults and optional secret/path meaning', () => {
    const props = parserProps()
    props.magicPdf.models_dir = '/models'
    const view = mount(<ParserServicesSection {...props} />)
    const sections = [...view.container.querySelectorAll('section')]
    const etl = sections.find((node) => node.querySelector('h2')?.textContent?.trim() === 'ETL4LLM 配置')!
    const docling = sections.find((node) => node.querySelector('h2')?.textContent?.trim() === 'Docling Serve 配置')!
    const magic = sections.find((node) => node.querySelector('h2')?.textContent?.trim() === 'MagicPDF 配置')!

    fill(input(etl, '超时（秒）'), '')
    expect(props.updateEtl4Llm).toHaveBeenLastCalledWith({ timeout_sec: 120 })
    expect(input(docling, 'API Key（可选）').value).toBe('docling***mask')
    fill(input(docling, 'API Key（可选）'), '')
    expect(props.updateDocling).toHaveBeenLastCalledWith({ api_key: '' })
    fill(input(magic, '模型目录'), '')
    expect(props.updateMagicPDF).toHaveBeenLastCalledWith({ models_dir: '' })
  })
})
