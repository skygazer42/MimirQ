// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const preference = vi.hoisted(() => ({ reduceMotion: false }))
vi.mock('framer-motion', async (importOriginal) => {
  const actual = await importOriginal<typeof import('framer-motion')>()
  return {
    ...actual,
    AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    useReducedMotion: () => preference.reduceMotion,
  }
})
vi.mock('@/components/auth-image', () => ({
  // eslint-disable-next-line @next/next/no-img-element -- Native image double exposes Markdown URL filtering in the DOM.
  AuthImage: ({ src, alt }: { src: string; alt: string }) => <img src={src} alt={alt} />,
}))

import { CinematicTypewriter } from './cinematic-typewriter'

const cleanup: Array<() => void> = []

function mount(props: React.ComponentProps<typeof CinematicTypewriter>) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const render = (next: React.ComponentProps<typeof CinematicTypewriter>) => {
    act(() => root.render(<CinematicTypewriter {...next} />))
  }
  render(props)
  cleanup.push(() => {
    act(() => root.unmount())
    container.remove()
  })
  return { container, render }
}

async function advance(ms = 2_000) {
  await act(async () => vi.advanceTimersByTime(ms))
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  preference.reduceMotion = false
})

afterEach(() => {
  for (const dispose of cleanup.splice(0).reverse()) dispose()
  vi.useRealTimers()
})

describe('CinematicTypewriter content lifetime', () => {
  it('shows every streamed update immediately with reduced motion', () => {
    preference.reduceMotion = true
    const onComplete = vi.fn()
    const view = mount({ content: '最初', isStreaming: true, onComplete })

    view.render({ content: '最初  😀\n新的内容', isStreaming: true, onComplete })

    expect(view.container.textContent).toBe('最初  😀\n新的内容')
    expect(onComplete).not.toHaveBeenCalled()
  })

  it('completes once when reduced-motion streaming ends and uses the current callback', () => {
    preference.reduceMotion = true
    const oldCallback = vi.fn()
    const onComplete = vi.fn()
    const view = mount({ content: '回答', isStreaming: true, onComplete: oldCallback })

    view.render({ content: '回答完成', isStreaming: false, onComplete })
    view.render({ content: '回答完成', isStreaming: false, onComplete })

    expect(view.container.textContent).toBe('回答完成')
    expect(oldCallback).not.toHaveBeenCalled()
    expect(onComplete).toHaveBeenCalledOnce()
  })

  it('wakes after completed content is appended or replaced', async () => {
    const onComplete = vi.fn()
    const view = mount({ content: 'First', onComplete })
    await advance()
    expect(onComplete).toHaveBeenCalledTimes(1)

    view.render({ content: 'First  😀', onComplete })
    await advance()
    expect(view.container.textContent).toBe('First  😀')
    expect(onComplete).toHaveBeenCalledTimes(2)

    view.render({ content: '替换后的回答', onComplete })
    await advance()
    expect(view.container.textContent).toBe('替换后的回答')
    expect(onComplete).toHaveBeenCalledTimes(3)
  })

  it('keeps the punctuation pause when content arrives during an active timer', async () => {
    const onComplete = vi.fn()
    const view = mount({ content: '甲，', isStreaming: true, onComplete })
    await advance(25)
    expect(view.container.textContent).toBe('甲，')

    view.render({ content: '甲，😀  乙', isStreaming: true, onComplete })
    await advance(100)
    expect(view.container.textContent).toBe('甲，')
    await advance()
    expect(view.container.textContent).toBe('甲，😀  乙')
    expect(onComplete).not.toHaveBeenCalled()

    view.render({ content: '甲，😀  乙', isStreaming: false, onComplete })
    await advance(60)
    expect(onComplete).toHaveBeenCalledOnce()
  })

  it('renders Markdown and suppresses raw HTML and executable links', () => {
    preference.reduceMotion = true
    const view = mount({
      content: '**回答** [文档](https://example.com/doc) [危险](javascript:alert%281%29) <script>bad()</script>',
    })

    expect(view.container.querySelector('strong')?.textContent).toBe('回答')
    expect(view.container.querySelector('a')?.getAttribute('href')).toBe('https://example.com/doc')
    expect(view.container.querySelectorAll('a')).toHaveLength(1)
    expect(view.container.querySelector('script')).toBeNull()
  })
})
