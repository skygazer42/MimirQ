// @vitest-environment jsdom
import React, { act, StrictMode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { PipelineOptionsProvider, usePipelineOptions } from './pipeline-options-context'

function Consumer() {
  const { options, updateOption } = usePipelineOptions()
  return <><output data-testid="chunk-size">{options.chunk_size}</output><button onClick={() => updateOption('chunk_size',600)}>更新长度</button></>
}

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  localStorage.clear()
})

describe('pipeline options storage hydration', () => {
  it('preserves stored options during Strict Mode effect replay and reads updates on remount', async () => {
    localStorage.setItem('mimirq_pipeline_options', JSON.stringify({ enabled: false, options: { chunk_size: 800, chunk_overlap: 120, reading_order_enabled: true } }))
    await act(async () => root.render(<StrictMode><PipelineOptionsProvider><Consumer /></PipelineOptionsProvider></StrictMode>))
    expect(container.querySelector('output')?.textContent).toBe('800')
    expect(JSON.parse(localStorage.getItem('mimirq_pipeline_options')!).options.chunk_size).toBe(800)
    await act(async () => container.querySelector('button')!.click())
    expect(JSON.parse(localStorage.getItem('mimirq_pipeline_options')!).options.chunk_size).toBe(600)
    await act(async () => root.unmount())
    root = createRoot(container)
    await act(async () => root.render(<StrictMode><PipelineOptionsProvider><Consumer /></PipelineOptionsProvider></StrictMode>))
    expect(container.querySelector('output')?.textContent).toBe('600')
    expect(JSON.parse(localStorage.getItem('mimirq_pipeline_options')!).options).toMatchObject({ chunk_size: 600, chunk_overlap: 120, reading_order_enabled: true })
  })
})
