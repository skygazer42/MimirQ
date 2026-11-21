// @vitest-environment happy-dom

import React, { act, StrictMode, useEffect } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { NextIntlClientProvider } from 'next-intl'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import commonMessages from '@/i18n/messages/zh-CN/common'
import { PipelineOptionsProvider, usePipelineOptions } from './pipeline-options-context'

const feedback = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock('sonner', () => ({ toast: feedback }))

const storageKey = 'mimirq_pipeline_options'
let root: Root
let container: HTMLDivElement
let importOptionsJson: ReturnType<typeof usePipelineOptions>['importJson']

function OptionsView() {
  const pipelineOptions = usePipelineOptions()
  const { enabled, options, updateOption } = pipelineOptions
  useEffect(() => {
    importOptionsJson = pipelineOptions.importJson
  }, [pipelineOptions.importJson])
  return (
    <div>
      <output>{`${enabled}:${options.chunk_size}`}</output>
      <button onClick={() => updateOption('chunk_size', 2048)}>Change chunk size</button>
    </div>
  )
}

describe('pipeline options persistence', () => {
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    localStorage.clear()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('cleans unsupported saved fields and disables active overrides before publishing them', async () => {
    localStorage.setItem(
      storageKey,
      JSON.stringify({
        enabled: true,
        options: { chunk_size: 4096, reading_order_enabled: false, sparse_enabled: true },
      }),
    )
    await act(async () =>
      root.render(
        <PipelineOptionsProvider>
          <OptionsView />
        </PipelineOptionsProvider>,
      ),
    )

    expect(container.querySelector('output')?.textContent).toBe('false:4096')
    const persisted = JSON.parse(localStorage.getItem(storageKey) as string)
    expect(persisted).toMatchObject({ enabled: false, options: { chunk_size: 4096, reading_order_enabled: false } })
    expect(persisted.options).not.toHaveProperty('sparse_enabled')
    expect(feedback.error).toHaveBeenCalledWith(expect.stringContaining('已清理并关闭覆盖'), { id: storageKey })
  })

  it.each([
    { chunk_size: 2048, sparse_enabled: true },
    { enabled: true, options: { chunk_size: 2048, colbert_enabled: true } },
  ])('rejects an import with unsupported fields and preserves the current configuration', async (imported) => {
    localStorage.setItem(storageKey, JSON.stringify({ enabled: true, options: { chunk_size: 4096 } }))
    await act(async () =>
      root.render(
        <PipelineOptionsProvider>
          <OptionsView />
        </PipelineOptionsProvider>,
      ),
    )
    const beforeImport = localStorage.getItem(storageKey)
    let result: ReturnType<typeof importOptionsJson>
    await act(async () => {
      result = importOptionsJson(JSON.stringify(imported))
    })

    expect(result!).toMatchObject({ ok: false, error: expect.stringContaining('不支持的管线字段') })
    expect(container.querySelector('output')?.textContent).toBe('true:4096')
    expect(localStorage.getItem(storageKey)).toBe(beforeImport)
  })

  it.each([false, true])('keeps saved options when StrictMode=%s', async (strict) => {
    localStorage.setItem(storageKey, JSON.stringify({ enabled: true, options: { chunk_size: 4096 } }))
    const provider = (
      <PipelineOptionsProvider>
        <OptionsView />
      </PipelineOptionsProvider>
    )

    await act(async () => root.render(strict ? <StrictMode>{provider}</StrictMode> : provider))

    expect(container.querySelector('output')?.textContent).toBe('true:4096')
    expect(JSON.parse(localStorage.getItem(storageKey) as string)).toMatchObject({
      enabled: true,
      options: { chunk_size: 4096 },
    })

    await act(async () => container.querySelector('button')!.click())
    expect(JSON.parse(localStorage.getItem(storageKey) as string)).toMatchObject({ options: { chunk_size: 2048 } })
  })

  it.each(['missing', 'corrupted', 'invalid options'])(
    'keeps the original defaults when saved JSON is %s',
    async (saved) => {
      if (saved === 'corrupted') localStorage.setItem(storageKey, '{broken')
      if (saved === 'invalid options') localStorage.setItem(storageKey, '{"enabled":true,"options":[]}')

      await act(async () =>
        root.render(
          <StrictMode>
            <PipelineOptionsProvider>
              <OptionsView />
            </PipelineOptionsProvider>
          </StrictMode>,
        ),
      )

      expect(container.querySelector('output')?.textContent).toBe('false:1000')
      expect(JSON.parse(localStorage.getItem(storageKey) as string)).toMatchObject({
        enabled: false,
        options: { chunk_size: 1000 },
      })
    },
  )

  it.each(['null', '[]', '42', '"text"', '{"options":null}', '{"options":[]}', '{"enabled":"true"}'])(
    'rejects invalid imported options without replacing saved preferences: %s',
    async (jsonText) => {
      localStorage.setItem(storageKey, JSON.stringify({ enabled: true, options: { chunk_size: 4096 } }))
      await act(async () =>
        root.render(
          <PipelineOptionsProvider>
            <OptionsView />
          </PipelineOptionsProvider>,
        ),
      )

      let result: ReturnType<typeof importOptionsJson>
      act(() => {
        result = importOptionsJson(jsonText)
      })

      expect(result!).toEqual({ ok: false, error: 'Invalid options shape' })
      expect(container.querySelector('output')?.textContent).toBe('true:4096')
      expect(JSON.parse(localStorage.getItem(storageKey)!)).toMatchObject({
        enabled: true,
        options: { chunk_size: 4096 },
      })
    },
  )

  it.each<[string, boolean]>([
    ['{"chunk_size":2048}', true],
    ['{"enabled":false,"options":{"chunk_size":2048}}', false],
  ])('imports supported option objects and persists the result: %s', async (jsonText, enabled) => {
    localStorage.setItem(storageKey, JSON.stringify({ enabled: true, options: { chunk_size: 4096 } }))
    await act(async () =>
      root.render(
        <PipelineOptionsProvider>
          <OptionsView />
        </PipelineOptionsProvider>,
      ),
    )

    let result: ReturnType<typeof importOptionsJson>
    act(() => {
      result = importOptionsJson(jsonText)
    })

    expect(result!).toEqual({ ok: true })
    expect(container.querySelector('output')?.textContent).toBe(`${enabled}:2048`)
    expect(JSON.parse(localStorage.getItem(storageKey)!)).toMatchObject({ enabled, options: { chunk_size: 2048 } })
  })

  it('keeps invalid import text open and saves only after a valid submission', async () => {
    localStorage.setItem(storageKey, JSON.stringify({ enabled: true, options: { chunk_size: 4096 } }))
    await act(async () =>
      root.render(
        <NextIntlClientProvider locale="zh-CN" messages={commonMessages}>
          <PipelineOptionsProvider>
            <PipelineOptionsPanel showJsonToolbar />
            <OptionsView />
          </PipelineOptionsProvider>
        </NextIntlClientProvider>,
      ),
    )
    const openImport = Array.from(container.querySelectorAll('button')).find((button) => button.textContent === '导入')!
    await act(async () => openImport.click())
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!
    const textarea = dialog.querySelector('textarea')!
    const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
    const submit = Array.from(dialog.querySelectorAll('button')).find((button) => button.textContent === '导入')!

    act(() => {
      setValue.call(textarea, 'null')
      textarea.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => submit.click())

    expect(feedback.error).toHaveBeenCalledWith('Invalid options shape')
    expect(feedback.success).not.toHaveBeenCalled()
    expect(dialog.isConnected).toBe(true)
    expect(textarea.value).toBe('null')
    expect(container.querySelector('output')?.textContent).toBe('true:4096')

    act(() => {
      setValue.call(textarea, '{"chunk_size":2048}')
      textarea.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => submit.click())

    expect(feedback.success).toHaveBeenCalledExactlyOnceWith('已导入管线 JSON')
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expect(container.querySelector('output')?.textContent).toBe('true:2048')
    expect(JSON.parse(localStorage.getItem(storageKey)!)).toMatchObject({ options: { chunk_size: 2048 } })
  })
})
