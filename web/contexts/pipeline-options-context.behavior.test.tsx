// @vitest-environment happy-dom

import React, { act, StrictMode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { PipelineOptionsProvider, usePipelineOptions } from './pipeline-options-context'

const storageKey = 'mimirq_pipeline_options'
let root: Root
let container: HTMLDivElement

function OptionsView() {
  const { enabled, options, updateOption } = usePipelineOptions()
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

  it.each(['missing', 'corrupted'])('keeps the original defaults when saved JSON is %s', async (saved) => {
    if (saved === 'corrupted') localStorage.setItem(storageKey, '{broken')

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
  })
})
