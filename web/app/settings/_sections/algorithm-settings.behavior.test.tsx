// @vitest-environment happy-dom

import React, { act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { normalizeRerankerProvider } from '@/lib/reranker-provider-options'
import { RagSection } from './rag-section'
import { LtrModelRegistrySection } from './ltr-model-registry-section'

type Rag = React.ComponentProps<typeof RagSection>['rag']
type LtrProps = React.ComponentProps<typeof LtrModelRegistrySection>
const cleanup: Array<() => void> = []

function ragConfig(extra: Partial<Rag> = {}): Rag {
  return {
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
    ...extra,
  }
}

function ltrProps(extra: Partial<LtrProps> = {}): LtrProps {
  return {
    ltrError: null,
    ltrMessage: null,
    ltrUploading: false,
    ltrUploadReady: true,
    ltrUploadResetKey: 0,
    ltrLoading: false,
    ltrBusyModelId: null,
    ltrModels: [
      {
        model_id: 'model-a',
        model_sha256: 'sha-a',
        size_bytes: 0,
        created_at: '2026-11-05T00:00:00Z',
        created_by: null,
        feature_spec_version: 1,
        feature_schema: 'features.v1',
        feature_names: ['score'],
        has_manifest: true,
        active: false,
      },
    ],
    onRegister: vi.fn(),
    onRefreshList: vi.fn(),
    onRollback: vi.fn(),
    onActivate: vi.fn(),
    onModelFileChange: vi.fn(),
    onManifestFileChange: vi.fn(),
    formatBytes: String,
    formatTime: String,
    shortId: String,
    ...extra,
  }
}

function mount(children: React.ReactNode) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const render = (content: React.ReactNode) => act(() => root.render(content))
  render(children)
  cleanup.push(() => {
    act(() => root.unmount())
    container.remove()
  })
  return { container, render }
}

function mountRag(extra: Partial<Rag> = {}) {
  const onPatch = vi.fn<(patch: Partial<Rag>) => void>()
  function Harness() {
    const [rag, setRag] = useState(ragConfig(extra))
    return (
      <RagSection
        rag={rag}
        updateRag={(patch) => {
          onPatch(patch)
          setRag((current) => ({ ...current, ...patch }))
        }}
      />
    )
  }
  return { ...mount(<Harness />), onPatch }
}

function field(container: ParentNode, label: string) {
  let node = [...container.querySelectorAll('div,span')].find((item) => item.textContent?.trim() === label)
  while (node && !node.querySelector('input')) node = node.parentElement ?? undefined
  const result = node?.querySelector('input')
  expect(result, label).toBeDefined()
  return result!
}

function fill(input: HTMLInputElement, value: string, parsed?: number) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    if (parsed !== undefined) expect(input.valueAsNumber).toBe(parsed)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

function button(scope: ParentNode, text: string) {
  const result = [...scope.querySelectorAll<HTMLButtonElement>('button')].find(
    (node) => node.textContent?.trim() === text,
  )
  expect(result, text).toBeDefined()
  return result!
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})
afterEach(() => {
  for (const dispose of cleanup.splice(0).reverse()) dispose()
  document.body.innerHTML = ''
})

describe('persisted RAG settings', () => {
  it.each([
    ['aliyun', 'dashscope', '通义千问重排'],
    ['late_interaction', 'colbert', 'ColBERT 后交互'],
  ])('represents the actual persisted %s backend alias', (alias, canonical, label) => {
    const view = mountRag({ reranker_provider: alias })
    expect(normalizeRerankerProvider(alias)).toBe(canonical)
    expect(view.container.querySelector('[role="combobox"]')?.textContent).toContain(label)
    expect(view.onPatch).not.toHaveBeenCalled()
  })

  it('preserves unknown raw selection behavior while keeping evaluation fallback policy', () => {
    const view = mountRag({ reranker_provider: 'custom-unknown' })
    expect(normalizeRerankerProvider('custom-unknown')).toBe('llm')
    expect(view.container.querySelector('[role="combobox"]')?.textContent).not.toContain('大模型重排')
    expect(view.onPatch).not.toHaveBeenCalled()
  })

  it.each([
    ['最多附图', 'image_append_max', '1e1', 10],
    ['重排数量', 'reranker_top_n', '2e1', 20],
    ['最小分块长度', 'chunk_min_chars', '3e1', 30],
  ] as const)('reads the full numeric input for %s', (label, key, raw, expected) => {
    const view = mountRag()
    fill(field(view.container, label), raw, expected)
    expect(view.onPatch).toHaveBeenLastCalledWith({ [key]: expected })
  })

  it('keeps explicit false, zero and slider budgets unchanged', () => {
    const view = mountRag()
    const bm25 = view.container.querySelector<HTMLButtonElement>('[aria-label="切换 BM25 检索"]')!
    act(() => bm25.click())
    expect(view.onPatch).toHaveBeenLastCalledWith({ bm25_index_enabled: false })
    fill(field(view.container, '最多附图'), '0', 0)
    expect(view.onPatch).toHaveBeenLastCalledWith({ image_append_max: 0 })
    fill(field(view.container, '最小分块长度'), '0', 0)
    expect(view.onPatch).toHaveBeenLastCalledWith({ chunk_min_chars: 0 })
    const ranges = [...view.container.querySelectorAll<HTMLInputElement>('input[type="range"]')]
    expect(ranges.map((input) => [input.min, input.max, input.getAttribute('step')])).toEqual([
      ['1', '20', null],
      ['0', '1', '0.1'],
      ['200', '4000', '100'],
      ['0', '1000', '50'],
    ])
    fill(ranges[1], '0', 0)
    expect(view.onPatch).toHaveBeenLastCalledWith({ similarity_threshold: 0 })
  })
})

describe('LTR registry controlled ownership', () => {
  it('prevents changing either file during a registration that owns the selected pair', () => {
    const view = mount(<LtrModelRegistrySection {...ltrProps({ ltrUploading: true })} />)
    expect(
      [...view.container.querySelectorAll<HTMLInputElement>('input[type="file"]')].map((node) => node.disabled),
    ).toEqual([true, true])
    expect(button(view.container, '注册中...').disabled).toBe(true)
  })

  it('uses the explicit reset key, rather than callback identity, for native file lifetime', () => {
    const props = ltrProps()
    const view = mount(<LtrModelRegistrySection {...props} />)
    const file = new File(['{}'], 'model.json', { type: 'application/json' })
    const transfer = new DataTransfer()
    transfer.items.add(file)
    const first = view.container.querySelector<HTMLInputElement>('input[type="file"]')!
    act(() => {
      first.files = transfer.files
      first.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(props.onModelFileChange).toHaveBeenCalledWith(file)

    view.render(<LtrModelRegistrySection {...props} onModelFileChange={vi.fn()} />)
    expect(view.container.querySelector('input[type="file"]')).toBe(first)
    expect(first.files?.[0]).toBe(file)
    view.render(<LtrModelRegistrySection {...props} ltrUploadResetKey={1} />)
    expect(view.container.querySelector('input[type="file"]')).not.toBe(first)
    expect(view.container.querySelector<HTMLInputElement>('input[type="file"]')?.files?.length).toBe(0)
  })

  it('keeps exact activation and rollback intents behind the existing confirmations', () => {
    const props = ltrProps()
    const view = mount(<LtrModelRegistrySection {...props} />)
    act(() => button(view.container, '激活').click())
    expect(props.onActivate).not.toHaveBeenCalled()
    act(() => button(document.querySelector('[role="alertdialog"]')!, '确认激活').click())
    expect(props.onActivate).toHaveBeenCalledExactlyOnceWith('model-a')
    act(() => button(view.container, '回滚').click())
    expect(props.onRollback).not.toHaveBeenCalled()
    act(() => button(document.querySelector('[role="alertdialog"]')!, '确认回滚').click())
    expect(props.onRollback).toHaveBeenCalledOnce()
  })

  it('retains visible load/action failures and current busy flags', () => {
    const props = ltrProps({
      ltrError: 'registry unavailable',
      ltrMessage: { type: 'error', text: 'activation denied' },
      ltrBusyModelId: 'model-a',
    })
    const view = mount(<LtrModelRegistrySection {...props} />)
    expect(view.container.textContent).toContain('registry unavailable')
    expect(view.container.textContent).toContain('activation denied')
    expect(button(view.container, '激活').disabled).toBe(true)
    expect(button(view.container, '回滚').disabled).toBe(true)
  })
})
