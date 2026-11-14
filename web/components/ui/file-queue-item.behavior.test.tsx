// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))

import { FileQueueItem } from './file-queue-item'

const cleanups: Array<() => void> = []

afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
})

describe('file queue filename recognition', () => {
  it.each(['report.constructor', 'report.__proto__', 'report.unsupported', 'report.pdf'])(
    'renders the queued filename %s',
    (name) => {
      ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
      const container = document.createElement('div')
      document.body.appendChild(container)
      const root = createRoot(container)
      cleanups.push(() => {
        act(() => root.unmount())
        container.remove()
      })

      act(() => root.render(<FileQueueItem file={{ id: 'queued-file', name, size: 128, status: 'pending' }} />))

      expect(container.textContent).toContain(name)
      expect(container.textContent).toContain('fileQueueItem.pending')
    },
  )
})
