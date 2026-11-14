// @vitest-environment happy-dom

import React, { act, useRef } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderHook } from '@/test/hook-harness'

import { useAnimatedNumber } from './use-animated-number'
import { useResizeObserver } from './use-resize-observer'

const preference = vi.hoisted(() => ({ reducedMotion: false }))

vi.mock('framer-motion', async (importOriginal) => ({
  ...(await importOriginal<typeof import('framer-motion')>()),
  useReducedMotion: () => preference.reducedMotion,
}))

const cleanups = new Set<() => void>()

afterEach(() => {
  for (const cleanup of cleanups) cleanup()
  cleanups.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.replaceChildren()
})

describe('useAnimatedNumber', () => {
  beforeEach(() => {
    preference.reducedMotion = false
  })

  it('updates the formatter while the spring is at rest', () => {
    let format = (value: number) => `Count: ${value}`
    const hook = renderHook(() => useAnimatedNumber(42, { format }))
    cleanups.add(hook.unmount)
    expect(hook.result.current).toBe('Count: 42')

    format = (value) => `${value} items`
    hook.rerender()

    expect(hook.result.current).toBe('42 items')
  })

  it('keeps the initial formatted value and default rounding', () => {
    const hook = renderHook(() => useAnimatedNumber(42.4))
    cleanups.add(hook.unmount)

    expect(hook.result.current).toBe(Math.round(42.4).toLocaleString())
  })

  it('shows changed targets immediately when reduced motion is requested', () => {
    preference.reducedMotion = true
    let target = 12
    const format = (value: number) => `Value: ${value}`
    const hook = renderHook(() => useAnimatedNumber(target, { format }))
    cleanups.add(hook.unmount)
    expect(hook.result.current).toBe('Value: 12')

    target = 24
    hook.rerender()

    expect(hook.result.current).toBe('Value: 24')
  })
})

function ResizeHarness({ target }: Readonly<{ target: string | null }>) {
  const ref = useRef<HTMLDivElement>(null)
  const dimensions = useResizeObserver(ref)

  return (
    <>
      <output>{`${dimensions.width}x${dimensions.height}`}</output>
      {target ? <div key={target} ref={ref} data-target={target} /> : null}
    </>
  )
}

function renderResizeHarness(target: string | null) {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const render = (nextTarget: string | null) => {
    act(() => root.render(<ResizeHarness target={nextTarget} />))
  }
  const unmount = () => {
    act(() => root.unmount())
    container.remove()
    cleanups.delete(unmount)
  }
  cleanups.add(unmount)
  render(target)
  return { container, render, unmount }
}

describe('useResizeObserver', () => {
  const observers: ControlledResizeObserver[] = []
  const frames = new Map<number, FrameRequestCallback>()
  let nextFrame = 0

  class ControlledResizeObserver {
    target: Element | null = null
    observe = vi.fn((target: Element) => {
      this.target = target
    })
    disconnect = vi.fn()

    constructor(private readonly callback: ResizeObserverCallback) {
      observers.push(this)
    }

    emit(width: number, height: number) {
      this.callback(
        [{ target: this.target, contentRect: { width, height } }] as ResizeObserverEntry[],
        this as unknown as ResizeObserver,
      )
    }
  }

  function flushFrames() {
    const callbacks = [...frames.values()]
    frames.clear()
    act(() => {
      for (const callback of callbacks) callback(0)
    })
  }

  beforeEach(() => {
    observers.length = 0
    frames.clear()
    nextFrame = 0
    vi.stubGlobal('ResizeObserver', ControlledResizeObserver)
    vi.stubGlobal(
      'requestAnimationFrame',
      vi.fn((callback: FrameRequestCallback) => {
        const id = ++nextFrame
        frames.set(id, callback)
        return id
      }),
    )
    vi.stubGlobal(
      'cancelAnimationFrame',
      vi.fn((id: number) => frames.delete(id)),
    )
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const [width, height] = this.dataset.target === 'second' ? [320, 240] : [600, 400]
      return { width, height } as DOMRect
    })
  })

  it('tracks a container that mounts, disappears and returns after an empty render', () => {
    const view = renderResizeHarness(null)
    expect(view.container.querySelector('output')?.textContent).toBe('0x0')
    expect(observers).toHaveLength(0)

    view.render('first')

    expect(observers).toHaveLength(1)
    expect(observers[0].observe).toHaveBeenCalledWith(view.container.querySelector('[data-target="first"]'))
    expect(view.container.querySelector('output')?.textContent).toBe('600x400')

    act(() => observers[0].emit(700, 500))
    view.render(null)
    expect(observers[0].disconnect).toHaveBeenCalledTimes(1)
    expect(frames.size).toBe(0)

    view.render('second')
    expect(observers).toHaveLength(2)
    expect(view.container.querySelector('output')?.textContent).toBe('320x240')
  })

  it('releases a replaced target and cancels its pending frame', () => {
    const view = renderResizeHarness('first')
    const firstObserver = observers[0]
    act(() => firstObserver.emit(700, 500))
    expect(frames.size).toBe(1)

    view.render('second')

    expect(firstObserver.disconnect).toHaveBeenCalledTimes(1)
    expect(frames.size).toBe(0)
    expect(observers).toHaveLength(2)
    expect(observers[1].observe).toHaveBeenCalledWith(view.container.querySelector('[data-target="second"]'))
    expect(view.container.querySelector('output')?.textContent).toBe('320x240')
  })

  it('coalesces resize notifications without restarting an unchanged target', () => {
    const view = renderResizeHarness('first')
    act(() => {
      observers[0].emit(500, 300)
      observers[0].emit(550, 350)
    })
    expect(frames.size).toBe(1)
    flushFrames()

    expect(view.container.querySelector('output')?.textContent).toBe('550x350')
    expect(observers).toHaveLength(1)
    expect(observers[0].disconnect).not.toHaveBeenCalled()

    act(() => observers[0].emit(0, 0))
    flushFrames()
    expect(view.container.querySelector('output')?.textContent).toBe('550x350')
  })

  it('disconnects and cancels the last pending frame on unmount', () => {
    const view = renderResizeHarness('first')
    act(() => observers[0].emit(700, 500))
    expect(frames.size).toBe(1)

    view.unmount()

    expect(observers[0].disconnect).toHaveBeenCalledTimes(1)
    expect(frames.size).toBe(0)
    expect(cancelAnimationFrame).toHaveBeenCalledTimes(1)
  })
})
