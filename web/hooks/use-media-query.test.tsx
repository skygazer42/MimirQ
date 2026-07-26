// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useMediaQuery } from './use-media-query'

type MockMediaQueryList = MediaQueryList & {
  _dispatch: (matches: boolean) => void
}

function createMockMediaQueryList(
  query: string,
  initialMatches = false
): MockMediaQueryList {
  let matches = initialMatches
  const listeners = new Set<(event: MediaQueryListEvent) => void>()

  const mql = {
    get matches() {
      return matches
    },
    media: query,
    onchange: null,
    addEventListener: (
      _type: 'change',
      listener: (event: MediaQueryListEvent) => void
    ) => {
      listeners.add(listener)
    },
    removeEventListener: (
      _type: 'change',
      listener: (event: MediaQueryListEvent) => void
    ) => {
      listeners.delete(listener)
    },
    addListener: (listener: (event: MediaQueryListEvent) => void) => {
      listeners.add(listener)
    },
    removeListener: (listener: (event: MediaQueryListEvent) => void) => {
      listeners.delete(listener)
    },
    dispatchEvent: () => true,
    _dispatch(nextMatches: boolean) {
      matches = nextMatches
      const event = { matches: nextMatches, media: query } as MediaQueryListEvent
      listeners.forEach((listener) => listener(event))
    },
  }

  return mql as MockMediaQueryList
}

function MediaQueryHarness({
  query = '(max-width: 1279.98px)',
}: Readonly<{ query?: string }>) {
  const matches = useMediaQuery(query)
  return (
    <div data-testid="media-query-state">{matches ? 'match' : 'no-match'}</div>
  )
}

describe('useMediaQuery', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    ;(
      globalThis as typeof globalThis & {
        IS_REACT_ACT_ENVIRONMENT?: boolean
      }
    ).IS_REACT_ACT_ENVIRONMENT = true
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('reads the current client snapshot on first render', () => {
    const matchMedia = vi.fn((query: string) =>
      createMockMediaQueryList(query, true)
    )
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: matchMedia,
    })

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      flushSync(() => {
        root.render(<MediaQueryHarness />)
      })
    })

    expect(matchMedia).toHaveBeenCalledWith('(max-width: 1279.98px)')
    expect(container.textContent).toContain('match')

    act(() => {
      root.unmount()
    })
  })

  it('updates when the media query match changes', () => {
    const mql = createMockMediaQueryList('(max-width: 1279.98px)', false)
    const matchMedia = vi.fn(() => mql)
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: matchMedia,
    })

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(<MediaQueryHarness />)
    })

    expect(container.textContent).toContain('no-match')

    act(() => {
      mql._dispatch(true)
    })

    expect(container.textContent).toContain('match')

    act(() => {
      root.unmount()
    })
  })
})
