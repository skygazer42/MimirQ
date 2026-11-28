// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { ToasterProps } from 'sonner'

const boundary = vi.hoisted(() => ({ toaster: vi.fn(), theme: 'light', dismiss: vi.fn() }))
vi.mock('next-themes', () => ({ useTheme: () => ({ resolvedTheme: boundary.theme }) }))
vi.mock('sonner', () => ({
  Toaster: (props: ToasterProps) => {
    boundary.toaster(props)
    return <button onClick={boundary.dismiss}>Close notification</button>
  },
}))

import { SonnerToaster } from './sonner-toaster'

describe('global feedback placement', () => {
  it.each(['light', 'dark'])('keeps %s feedback away from modal headings and mobile save actions', (theme) => {
    boundary.theme = theme
    renderToStaticMarkup(<SonnerToaster />)
    expect(boundary.toaster).toHaveBeenLastCalledWith(
      expect.objectContaining({
        theme,
        position: 'top-center',
        offset: { top: 'max(12px, env(safe-area-inset-top))' },
        mobileOffset: {
          top: 'max(8px, env(safe-area-inset-top))',
          right: 16,
          left: 16,
        },
        closeButton: true,
        visibleToasts: 1,
        style: { pointerEvents: 'none' },
        toastOptions: expect.objectContaining({
          classNames: expect.objectContaining({
            content: expect.stringContaining('max-h-10'),
            closeButton: 'pointer-events-auto',
          }),
        }),
      }),
    )
  })

  it('dismisses feedback without passing a pointer press to the modal outside-click handler', () => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    const outsidePointer = vi.fn()
    document.addEventListener('pointerdown', outsidePointer)
    try {
      act(() => root.render(<SonnerToaster />))
      const close = container.querySelector('button')!
      act(() => {
        close.dispatchEvent(new Event('pointerdown', { bubbles: true }))
        close.click()
      })
      expect(outsidePointer).not.toHaveBeenCalled()
      expect(boundary.dismiss).toHaveBeenCalledOnce()
    } finally {
      document.removeEventListener('pointerdown', outsidePointer)
      act(() => root.unmount())
      container.remove()
    }
  })
})
