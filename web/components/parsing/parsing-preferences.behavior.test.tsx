// @vitest-environment happy-dom

import React, { act, StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/contexts/parser-backend-context', () => ({
  useParserBackendPreference: () => ({ parserBackend: 'auto', setParserBackend: vi.fn() }),
}))

import { useParsingPageState } from './use-parsing-page-state'
import type { ParsedFile } from './parsing-types'

const cleanups: Array<() => void> = []

function mount(strict = false) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const result = React.createRef<ReturnType<typeof useParsingPageState>>()
  cleanups.push(() => {
    act(() => root.unmount())
    container.remove()
  })
  function Probe() {
    const [files, setFiles] = useState<ParsedFile[]>([])
    const state = useParsingPageState({ files, setFiles })
    React.useImperativeHandle(result, () => state, [state])
    return null
  }
  act(() =>
    root.render(
      strict ? (
        <StrictMode>
          <Probe />
        </StrictMode>
      ) : (
        <Probe />
      ),
    ),
  )
  return result as { current: ReturnType<typeof useParsingPageState> }
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  localStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
  for (const cleanup of cleanups.splice(0)) cleanup()
})

const preferences = [
  ['imageCaptionEnabled', 'mimirq_parsing_image_caption_enabled'],
  ['imageOcrEnabled', 'mimirq_parsing_image_ocr_enabled'],
  ['vlmCorrectionEnabled', 'mimirq_parsing_vlm_correction_enabled'],
] as const

describe('parsing preferences', () => {
  it.each(preferences)('restores %s before StrictMode can persist its initial default', (field, key) => {
    localStorage.setItem(key, 'true')
    const state = mount(true)

    expect(state.current[field]).toBe(true)
    expect(localStorage.getItem(key)).toBe('true')
  })

  it.each(preferences)('keeps ordinary mounting for saved %s', (field, key) => {
    localStorage.setItem(key, 'true')
    const state = mount()

    expect(state.current[field]).toBe(true)
    expect(localStorage.getItem(key)).toBe('true')
  })

  it('retains false defaults when there is no saved preference', () => {
    const state = mount(true)

    for (const [field, key] of preferences) {
      expect(state.current[field]).toBe(false)
      expect(localStorage.getItem(key)).toBe('false')
    }
  })

  it('persists an explicit user change back to false', () => {
    localStorage.setItem('mimirq_parsing_image_ocr_enabled', 'true')
    const state = mount()
    act(() => state.current.setImageOcrEnabled(false))

    expect(state.current.imageOcrEnabled).toBe(false)
    expect(localStorage.getItem('mimirq_parsing_image_ocr_enabled')).toBe('false')
  })

  it('keeps the workspace available when optional preference reads are denied', () => {
    vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    const state = mount()

    expect(state.current.imageOcrEnabled).toBe(false)
  })

  it('keeps user choices in memory when optional preference writes are denied', () => {
    vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    const state = mount()
    act(() => state.current.setImageOcrEnabled(true))

    expect(state.current.imageOcrEnabled).toBe(true)
  })
})
