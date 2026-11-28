// @vitest-environment happy-dom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/contexts/pipeline-capabilities-context', () => ({
  usePipelineCapabilities: () => ({
    capabilities: { pdf_backends: [{ name: 'mineru', notes: '服务未配置' }] },
    loading: false,
    error: null,
    refresh: vi.fn(),
    parserBackendAvailable: (backend: string) => backend === 'docling',
  }),
}))

import { ParsingParserPicker } from './parsing-parser-picker'

let root: Root
let container: HTMLDivElement

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.restoreAllMocks()
})

async function render(filename = 'report.pdf', disabled = false, onChange = vi.fn()) {
  await act(async () =>
    root.render(<ParsingParserPicker value="auto" filename={filename} disabled={disabled} onChange={onChange} />),
  )
  return container.querySelector('button')!
}

async function open(filename = 'report.pdf', onChange = vi.fn()) {
  const trigger = await render(filename, false, onChange)
  await act(async () => trigger.click())
  return document.querySelector<HTMLElement>('[role="dialog"]')!
}

function card(name: string) {
  return Array.from(document.querySelectorAll<HTMLButtonElement>('[aria-label="解析器列表"] button')).find((button) =>
    button.textContent?.includes(name),
  )!
}

describe('parsing parser picker', () => {
  it('uses a modal, preserves service availability, and applies one selection before closing', async () => {
    const change = vi.fn()
    const dialog = await open('report.pdf', change)
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(card('自动选择').getAttribute('aria-pressed')).toBe('true')
    expect(card('MinerU').disabled).toBe(true)
    expect(card('MinerU').textContent).toContain('服务未配置')
    expect(card('Docling').disabled).toBe(false)
    await act(async () => card('Docling').click())
    expect(change).toHaveBeenCalledExactlyOnceWith('docling')
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  })

  it('filters by parser capabilities while retaining file incompatibility', async () => {
    const dialog = await open('report.md')
    expect(card('Docling').disabled).toBe(true)
    expect(card('Docling').textContent).toContain('不支持当前格式')
    const input = dialog.querySelector<HTMLInputElement>('input')!
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    await act(async () => {
      setValue.call(input, 'Docling')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(dialog.querySelectorAll('[aria-label="解析器列表"] button')).toHaveLength(1)
    expect(card('Docling').disabled).toBe(true)
    await act(async () => {
      setValue.call(input, 'no matching parser')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(dialog.textContent).toContain('没有匹配的解析器')
  })

  it('locks the picker during editing or parsing and does not reopen it when the lock ends', async () => {
    await open()
    const trigger = await render('report.pdf', true)
    expect(trigger.disabled).toBe(true)
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    await render()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  })
})
