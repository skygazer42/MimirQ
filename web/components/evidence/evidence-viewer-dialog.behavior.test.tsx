// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Citation } from '@/types'

const controlled = vi.hoisted(() => ({ openDocument: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('@/store/document-view', () => ({ useDocumentView: () => ({ openDocument: controlled.openDocument }) }))
vi.mock('sonner', () => ({ toast: controlled.toast }))

import { EvidenceViewerDialog } from './evidence-viewer-dialog'

let root: Root
const initialClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
const citation: Citation = {
  document_id: 'doc-id',
  document_name: '  😀文档  ',
  chunk_content: '  原文\n',
  relevance_score: 0,
  page_number: 0,
  evidence_start_char: 0,
  evidence_end_char: 2,
}

function render(value: React.ComponentProps<typeof EvidenceViewerDialog>['citation'] = citation, open = true) {
  act(() => root.render(<EvidenceViewerDialog open={open} citation={value} onOpenChange={vi.fn()} />))
}

function button(label: string) {
  const element = Array.from(document.querySelectorAll('button')).find((item) => item.textContent?.trim() === label)
  if (element === undefined) throw new Error(`Missing button: ${label}`)
  return element
}

beforeEach(() => {
  vi.clearAllMocks()
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  document.body.replaceChildren()
  if (initialClipboard === undefined) Reflect.deleteProperty(navigator, 'clipboard')
  else Object.defineProperty(navigator, 'clipboard', initialClipboard)
})

describe('evidence viewer real clipboard and source contracts', () => {
  it('treats actual server null metadata as absent without inventing page or range labels', () => {
    const fromServer = {
      ...citation,
      chunk_id: null,
      page_number: null,
      start_char: null,
      end_char: null,
      evidence_start_char: null,
      evidence_end_char: null,
      rerank_score: null,
    }
    render(fromServer)
    expect(document.querySelector('[role="dialog"] h2')?.textContent).not.toContain('P.null')
    expect(document.querySelector('[role="dialog"]')?.textContent).not.toContain('null..null')
    expect(document.querySelector('[role="dialog"]')?.textContent).not.toContain('重排得分')
    act(() => button('打开文档').click())
    expect(controlled.openDocument).toHaveBeenCalledWith('doc-id', undefined, undefined, expect.any(Object))
  })

  it('preserves raw source and page zero in the heading and document navigation', () => {
    render()
    expect(document.querySelector('[role="dialog"] h2')?.textContent).toContain('P.0')
    expect(document.querySelector('pre')?.textContent).toBe(citation.chunk_content)
    act(() => button('打开文档').click())
    expect(controlled.openDocument).toHaveBeenCalledWith('doc-id', undefined, { start: 0, end: 2 }, expect.any(Object))
  })

  it.each(['unavailable', 'rejected'])('shows an actionable copy failure for %s clipboard', async (failure) => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value:
        failure === 'unavailable' ? undefined : { writeText: vi.fn().mockRejectedValue(new Error('用户拒绝复制')) },
    })
    render()
    await act(async () => button('复制 JSON').click())
    expect(document.querySelector('[role="alert"]')?.textContent).toContain('复制失败')
    expect(button('复制 JSON').disabled).toBe(false)
    expect(controlled.toast.success).not.toHaveBeenCalled()
  })

  it('does not report an old clipboard completion after selection replacement or closing', async () => {
    let complete!: () => void
    const writeText = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          complete = resolve
        }),
    )
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    render()
    act(() => button('复制 JSON').click())
    expect(writeText).toHaveBeenCalledExactlyOnceWith(JSON.stringify(citation, null, 2))
    render({ ...citation, document_id: 'next-doc' })
    render(citation, false)
    await act(async () => complete())
    expect(controlled.toast.success).not.toHaveBeenCalled()
  })
})
