// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('framer-motion', () => ({
  AnimatePresence: ({ children }: { children: React.ReactNode }) => children,
  motion: {
    div: ({
      initial: _initial,
      animate: _animate,
      exit: _exit,
      ...props
    }: React.HTMLAttributes<HTMLDivElement> & {
      initial?: unknown
      animate?: unknown
      exit?: unknown
    }) => <div {...props} />,
  },
  useReducedMotion: () => true,
}))

import { VoiceModeOverlay } from './voice-mode-overlay'

type RecognitionResult = { isFinal: boolean; 0: { transcript: string } }
type ResultEvent = { resultIndex: number; results: RecognitionResult[] }

class Recognition {
  static instances: Recognition[] = []
  continuous = false
  interimResults = false
  lang = ''
  onresult: ((event: ResultEvent) => void) | null = null
  onend: (() => void) | null = null
  onerror: ((event: { error: string }) => void) | null = null
  start = vi.fn()
  stop = vi.fn()

  constructor() {
    Recognition.instances.push(this)
  }
}

const cleanup: Array<() => void> = []

function mount() {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const onSend = vi.fn()
  const onClose = vi.fn()
  function render(isOpen = true, send = onSend) {
    act(() => root.render(<VoiceModeOverlay isOpen={isOpen} onClose={onClose} onSend={send} />))
  }
  let mounted = true
  const unmount = () => {
    if (!mounted) return
    mounted = false
    act(() => root.unmount())
    container.remove()
  }
  cleanup.push(unmount)
  render()
  return { container, onSend, onClose, render, unmount }
}

function button(container: HTMLElement, label: string) {
  const target = container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)
  expect(target).not.toBeNull()
  return target!
}

function final(transcript: string): RecognitionResult {
  return { isFinal: true, 0: { transcript } }
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  Recognition.instances = []
  Object.defineProperty(window, 'webkitSpeechRecognition', { configurable: true, value: Recognition })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
})

afterEach(() => {
  for (const dispose of cleanup.splice(0).reverse()) dispose()
  delete (window as Window & { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

describe('VoiceModeOverlay recognition lifetime', () => {
  it('disables listening when recognition is unavailable', () => {
    delete (window as Window & { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition
    const view = mount()

    expect(button(view.container, '开始语音输入').disabled).toBe(true)
    expect(view.container.textContent).toContain('不支持语音输入')
  })

  it.each(['close', 'unmount'] as const)('stops the microphone on %s', (action) => {
    const view = mount()
    const recognition = Recognition.instances[0]!
    act(() => button(view.container, '开始语音输入').click())

    if (action === 'close') view.render(false)
    else view.unmount()

    expect(recognition.start).toHaveBeenCalledOnce()
    expect(recognition.stop).toHaveBeenCalledOnce()
    expect(recognition.onresult).toBeNull()
    expect(view.onSend).not.toHaveBeenCalled()
  })

  it('keeps the active recognizer when the send callback is recreated', () => {
    const view = mount()
    const recognition = Recognition.instances[0]!
    act(() => button(view.container, '开始语音输入').click())

    view.render(true, vi.fn())

    expect(Recognition.instances).toHaveLength(1)
    act(() => button(view.container, '停止语音输入').click())
    expect(recognition.stop).toHaveBeenCalledOnce()
  })

  it('includes every final phrase and waits for final recognition after stop', () => {
    const view = mount()
    const recognition = Recognition.instances[0]!
    act(() => button(view.container, '开始语音输入').click())
    act(() => recognition.onresult?.({ resultIndex: 0, results: [final('第一句')] }))
    act(() => button(view.container, '停止语音输入').click())

    expect(view.onSend).not.toHaveBeenCalled()
    act(() => {
      recognition.onresult?.({ resultIndex: 1, results: [final('第一句'), final('，第二句')] })
      recognition.onend?.()
    })

    expect(view.onSend.mock.calls).toEqual([['第一句，第二句']])
  })

  it('ignores late results after close and opens a fresh idle session', () => {
    const view = mount()
    const recognition = Recognition.instances[0]!
    act(() => button(view.container, '开始语音输入').click())
    const lateResult = recognition.onresult!
    view.render(false)
    act(() => lateResult({ resultIndex: 0, results: [final('旧会话')] }))

    view.render(true)

    expect(button(view.container, '开始语音输入').disabled).toBe(false)
    expect(view.container.textContent).not.toContain('旧会话')
    expect(view.onSend).not.toHaveBeenCalled()
  })

  it('uses the existing continuous Chinese recognition options', () => {
    mount()
    expect(Recognition.instances[0]).toMatchObject({ continuous: true, interimResults: true, lang: 'zh-CN' })
  })

  it('sends completed speech once through the latest callback', () => {
    const view = mount()
    const recognition = Recognition.instances[0]!
    const latest = vi.fn()
    act(() => button(view.container, '开始语音输入').click())
    view.render(true, latest)
    act(() => recognition.onresult?.({ resultIndex: 0, results: [final('完整内容')] }))
    expect(latest).not.toHaveBeenCalled()
    act(() => button(view.container, '停止语音输入').click())

    act(() => {
      recognition.onend?.()
      recognition.onend?.()
    })

    expect(latest.mock.calls).toEqual([['完整内容']])
    expect(view.onSend).not.toHaveBeenCalled()
  })

  it('keeps recognition errors visible and does not send the failed session', () => {
    const view = mount()
    const recognition = Recognition.instances[0]!
    act(() => button(view.container, '开始语音输入').click())
    act(() => {
      recognition.onerror?.({ error: 'not-allowed' })
      recognition.onend?.()
    })

    expect(view.container.querySelector('[role="alert"]')?.textContent).toContain('语音输入失败')
    expect(button(view.container, '开始语音输入').disabled).toBe(false)
    expect(view.onSend).not.toHaveBeenCalled()
  })
})
