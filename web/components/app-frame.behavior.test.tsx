// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))

vi.mock('@/components/navbar', () => ({
  Navbar: ({ isSidebarOpen }: { isSidebarOpen: boolean }) => (
    <div data-testid="navbar" data-open={String(isSidebarOpen)} />
  ),
}))

vi.mock('@/components/ui/app-background', () => ({
  AppBackground: () => null,
}))

vi.mock('@/store/document-view', () => ({
  useDocumentView: () => ({ isOpen: false }),
}))

import { AppFrame } from './app-frame'

function renderFrame(isMobile: boolean) {
  ;(
    globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true

  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({ matches: isMobile }),
  })

  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)

  act(() => {
    root.render(<AppFrame>content</AppFrame>)
  })

  return {
    container,
    unmount() {
      act(() => root.unmount())
      container.remove()
    },
  }
}

describe('AppFrame responsive sidebar', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    document.body.replaceChildren()
  })

  it('starts with page content available on mobile', () => {
    const view = renderFrame(true)

    expect(view.container.querySelector('[data-testid="navbar"]')?.getAttribute('data-open')).toBe('false')
    expect(view.container.querySelector('#main-content')?.parentElement?.hasAttribute('aria-hidden')).toBe(false)

    view.unmount()
  })

  it('preserves the desktop-open default', () => {
    const view = renderFrame(false)

    expect(view.container.querySelector('[data-testid="navbar"]')?.getAttribute('data-open')).toBe('true')

    view.unmount()
  })
})
