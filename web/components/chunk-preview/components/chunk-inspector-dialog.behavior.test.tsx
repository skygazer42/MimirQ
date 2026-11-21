// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChunkPreviewItem } from '@/types'

const feedback = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string, values?: { chars: number; lines: number }) =>
    key === 'chunkInspector.contentStats' && values !== undefined
      ? `${values.chars} chars / ${values.lines} lines`
      : key,
}))
vi.mock('sonner', () => ({ toast: feedback }))
vi.mock('@/contexts/pipeline-options-context', () => ({
  usePipelineOptions: () => ({ enabled: true, options: { embedding_context_prefix_enabled: true } }),
}))

import { ChunkInspectorDialog } from './chunk-inspector-dialog'

const roots: Root[] = []
const initialClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')

function mount() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.push(root)
  const save = vi.fn()
  const item: ChunkPreviewItem = {
    index: 0,
    content: '  source\n\n',
    length: 10,
    start_index: 0,
    end_index: 10,
    metadata: { header_path: 'Original' },
  }
  function render(chunk = item, position = 0, open = true) {
    act(() =>
      root.render(
        <ChunkInspectorDialog
          open={open}
          onOpenChange={vi.fn()}
          chunk={chunk}
          position={position}
          sourceFilename="source.md"
          onSave={save}
          onReset={vi.fn()}
        />,
      ),
    )
  }
  render()
  return { save, item, render }
}

function textarea(label: string) {
  const element = document.querySelector<HTMLTextAreaElement>(`textarea[aria-label="${label}"]`)
  if (element === null) throw new Error(`Missing textarea: ${label}`)
  return element
}

function button(label: string) {
  const element = Array.from(document.querySelectorAll('button')).find((item) => item.textContent?.trim() === label)
  if (element === undefined) throw new Error(`Missing button: ${label}`)
  return element
}

function changeTextarea(label: string, value: string) {
  const element = textarea(label)
  const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
  act(() => {
    setValue.call(element, value)
    element.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

function changeMetadata(value: string) {
  changeTextarea('chunkInspector.metadataLabel', value)
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
})

afterEach(() => {
  for (const root of roots.splice(0)) act(() => root.unmount())
  document.body.replaceChildren()
  if (initialClipboard === undefined) Reflect.deleteProperty(navigator, 'clipboard')
  else Object.defineProperty(navigator, 'clipboard', initialClipboard)
  vi.restoreAllMocks()
})

describe('actual metadata draft validation', () => {
  it('keeps unsaved body and invalid metadata drafts when the same entity receives a new object', () => {
    const { item, render } = mount()
    changeTextarea('chunkInspector.contentLabel', '  unsaved 😀 body\n')
    changeMetadata('{')

    render({ ...item, metadata: { ...item.metadata } })

    expect(textarea('chunkInspector.contentLabel').value).toBe('  unsaved 😀 body\n')
    expect(textarea('chunkInspector.metadataLabel').value).toBe('{')
    expect(button('chunkInspector.save').disabled).toBe(true)
  })

  it('starts a fresh draft when another real chunk is opened at the same source position', () => {
    const { item, render } = mount()
    changeTextarea('chunkInspector.contentLabel', 'unsaved body')
    render({ ...item, index: 9, content: 'different entity' })
    expect(textarea('chunkInspector.contentLabel').value).toBe('different entity')
  })

  it('discards an explicitly closed draft and reopens with the current entity content', () => {
    const { item, render } = mount()
    changeTextarea('chunkInspector.contentLabel', 'cancelled body')
    render(item, 0, false)
    render({ ...item, content: 'current source' })
    expect(textarea('chunkInspector.contentLabel').value).toBe('current source')
  })

  it('counts actual source characters and newline conventions without trimming the draft', () => {
    mount()
    changeTextarea('chunkInspector.contentLabel', '😀\r\n𠮷\r甲\n')
    expect(document.body.textContent).toContain('7 chars / 4 lines')
  })

  it('associates the invalid metadata feedback with the actual input', () => {
    mount()
    changeMetadata('{')
    const input = textarea('chunkInspector.metadataLabel')
    const describedBy = input.getAttribute('aria-describedby')
    expect(describedBy).not.toBeNull()
    expect(document.getElementById(describedBy!)?.getAttribute('role')).toBe('alert')
  })

  it('copies the actual preview before reporting success', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    mount()
    act(() =>
      button('chunkInspector.embeddingTab').dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 })),
    )
    await act(async () => button('chunkInspector.copyEmbedding').click())
    expect(writeText).toHaveBeenCalledExactlyOnceWith('[Section] Original\n  source\n\n')
    expect(feedback.success).toHaveBeenCalledExactlyOnceWith('chunkInspector.copySuccess')
    expect(feedback.error).not.toHaveBeenCalled()
  })

  it('reports a rejected clipboard write without reporting success', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('Permission denied'))
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    mount()
    act(() =>
      button('chunkInspector.embeddingTab').dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 })),
    )
    await act(async () => button('chunkInspector.copyEmbedding').click())
    expect(feedback.error).toHaveBeenCalledExactlyOnceWith('chunkInspector.copyFailed')
    expect(feedback.success).not.toHaveBeenCalled()
  })

  it('keeps a blank JSON draft visible and prevents saving it as an empty object', () => {
    const { save } = mount()
    changeMetadata('')
    expect(textarea('chunkInspector.metadataLabel').value).toBe('')
    expect(button('chunkInspector.save').disabled).toBe(true)
    expect(document.body.textContent).not.toContain('chunkInspector.metadataOk')
    act(() => button('chunkInspector.save').click())
    expect(save).not.toHaveBeenCalled()
  })

  it('does not reuse an original header after the draft explicitly clears it', () => {
    mount()
    changeMetadata('{"header_path":null}')
    act(() =>
      button('chunkInspector.embeddingTab').dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 })),
    )
    expect(textarea('chunkInspector.embeddingLabel').value).toBe('  source\n\n')
  })

  it('saves actual zero/false fields and exact content after a valid draft replaces an invalid one', () => {
    const { save, item } = mount()
    changeMetadata('')
    changeMetadata('{"header_path":"0","weight":0,"reviewed":false}')
    act(() => button('chunkInspector.save').click())
    expect(save).toHaveBeenCalledExactlyOnceWith({
      content: '  source\n\n',
      metadata: { header_path: '0', weight: 0, reviewed: false },
    })
    expect(item.metadata).toEqual({ header_path: 'Original' })
  })
})
