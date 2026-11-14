// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Message } from '@/types/chat'
import type { MessageFeedback } from '@/types/feedback'
import type { Citation } from '@/types/processing'

const boundary = vi.hoisted(() => ({
  createFeedback: vi.fn(),
  toRegressionCase: vi.fn(),
  getDocument: vi.fn(),
  openDocument: vi.fn(),
  prefetch: vi.fn(),
  push: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('framer-motion', async (importOriginal) => {
  const actual = await importOriginal<typeof import('framer-motion')>()
  return { ...actual, useReducedMotion: () => true }
})
vi.mock('@/lib/api', () => ({
  documentApi: { get: boundary.getDocument },
  feedbackApi: { create: boundary.createFeedback, toRegressionCase: boundary.toRegressionCase },
}))
vi.mock('@/lib/api/documents', () => ({ documentApi: { get: boundary.getDocument } }))
vi.mock('@/lib/api/feedback', () => ({
  feedbackApi: { create: boundary.createFeedback, toRegressionCase: boundary.toRegressionCase },
}))
vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ push: boundary.push }) }))
vi.mock('@/store/document-view', () => ({ useDocumentView: () => ({ openDocument: boundary.openDocument }) }))
vi.mock('@/lib/document-view-prefetch', () => ({ prefetchDocumentView: boundary.prefetch }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn() }))
vi.mock('sonner', () => ({ toast: { success: boundary.success, error: boundary.error } }))
vi.mock('@/components/auth-image', () => ({
  // eslint-disable-next-line @next/next/no-img-element -- Native image double exposes Markdown URL filtering in the DOM.
  AuthImage: ({ src, alt }: { src: string; alt: string }) => <img src={src} alt={alt} />,
  useResolvedAuthAssetUrl: (src: string | null) => src,
}))

import { AUTH_SCOPE_CHANGED_EVENT, setAccessToken, setAuthSession } from '@/lib/auth-storage'
import { ChatMessageItem } from './message-item'

const MESSAGE_ID = '6bf3f764-cf70-4f90-a747-65773fe43f16'
const cleanup: Array<() => void> = []
const token = { access_token: 'same-token', token_type: 'bearer', expires_in: 3600 }
const profile = {
  id: 'user-a',
  email: 'user@example.com',
  username: 'user-a',
  is_active: true,
  created_at: '2026-11-05T00:00:00Z',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function assistant(extra: Partial<Message> = {}): Message {
  return { id: MESSAGE_ID, role: 'assistant', content: '回答', created_at: '2026-11-05T00:00:00Z', ...extra }
}

function feedback(rating = 2): MessageFeedback {
  return {
    id: 'feedback-a',
    tenant_id: 'tenant-a',
    conversation_id: 'conversation-a',
    message_id: MESSAGE_ID,
    account_id: 'account-a',
    rating,
    tags: ['review'],
    reason: '可复现问题',
    expected_answer: '正确答案',
    created_at: '2026-11-05T00:00:00Z',
    updated_at: '2026-11-05T00:00:00Z',
  }
}

function citation(extra: Partial<Citation> = {}): Citation {
  return {
    document_id: 'document-a',
    document_name: '参考文档',
    chunk_id: 'chunk-a',
    chunk_content: '证据内容',
    relevance_score: 0.8,
    evidence_start_char: 12,
    evidence_end_char: 22,
    page_number: 3,
    ...extra,
  }
}

function mount(message = assistant(), variant: 'default' | 'minimal' = 'default') {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  let mounted = true
  act(() => root.render(<ChatMessageItem message={message} variant={variant} />))
  const unmount = () => {
    if (!mounted) return
    mounted = false
    act(() => root.unmount())
    container.remove()
  }
  cleanup.push(unmount)
  return { container, unmount }
}

function button(container: ParentNode, label: string) {
  const target = Array.from(container.querySelectorAll('button')).find(
    (item) => item.getAttribute('aria-label') === label || item.textContent?.trim() === label,
  )
  expect(target, `button ${label}`).toBeDefined()
  return target as HTMLButtonElement
}

async function rate(container: ParentNode, value: number) {
  for (const details of container.querySelectorAll('details')) details.open = true
  await act(async () => button(container, `rate-${value}`).click())
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  boundary.createFeedback.mockResolvedValue(feedback())
})

afterEach(() => {
  for (const dispose of cleanup.splice(0).reverse()) dispose()
  document.body.innerHTML = ''
})

describe('message rendering contracts', () => {
  it.each(['default', 'minimal'] as const)(
    'opens and prefetches backend inline citations in the %s view',
    (variant) => {
      const view = mount(
        assistant({
          content: '回答 [来源](mimirq-citation://evidence?document_id=document-a&chunk_id=chunk-a)',
          citations: [citation()],
        }),
        variant,
      )
      const link = button(view.container, '来源')

      act(() => {
        link.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))
        link.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
        link.click()
      })

      expect(boundary.prefetch).toHaveBeenCalledOnce()
      expect(boundary.prefetch).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'document-a', chunkId: 'chunk-a' }),
      )
      expect(boundary.openDocument).toHaveBeenCalledWith(
        'document-a',
        'chunk-a',
        { start: 12, end: 22 },
        expect.objectContaining({
          activeTab: 'preview',
          sourceContext: {
            kind: 'chat-citation',
            messageId: MESSAGE_ID,
            documentId: 'document-a',
            chunkId: 'chunk-a',
            documentName: '参考文档',
            chunkContent: '证据内容',
            chunkIndex: null,
            pageNumber: 3,
          },
        }),
      )
    },
  )

  it('keeps unsafe schemes, raw HTML and blocked images out of the message DOM', () => {
    const view = mount(
      assistant({
        content:
          '[正常](https://example.com/doc) [危险](javascript:alert%281%29) [无效引用](mimirq-citation://evidence) ![blocked](http://127.0.0.1/private.png) <script>bad()</script>',
      }),
    )

    const links = view.container.querySelectorAll('a')
    expect(links).toHaveLength(1)
    expect(links[0].getAttribute('href')).toBe('https://example.com/doc')
    expect(links[0].getAttribute('rel')).toBe('noopener noreferrer')
    expect(view.container.querySelector('script')).toBeNull()
    expect(view.container.querySelector('img')).toBeNull()
    expect(Array.from(view.container.querySelectorAll('button')).some((item) => item.textContent === '无效引用')).toBe(
      false,
    )
  })

  it('does not project an absent confidence score as evidence failure', () => {
    const view = mount(assistant({ message_metadata: { confidence_score: null } }))

    expect(view.container.textContent).not.toContain('证据不足')
    expect(view.container.textContent).not.toContain('0%')
  })

  it('preserves an explicit zero confidence score', () => {
    const view = mount(assistant({ message_metadata: { confidence_score: 0 } }))

    expect(view.container.textContent).toContain('证据不足')
    expect(view.container.textContent).toContain('0%')
  })

  it('opens table evidence through the existing dialog with its citation context', () => {
    const view = mount(assistant({ citations: [citation({ hit_type: 'table' })] }))

    act(() => button(view.container, 'view-evidence').click())
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('Table Evidence')
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('证据内容')
    act(() => button(document, '打开文档').click())

    expect(boundary.openDocument).toHaveBeenCalledWith(
      'document-a',
      'chunk-a',
      { start: 12, end: 22 },
      expect.objectContaining({ sourceContext: expect.objectContaining({ messageId: MESSAGE_ID }) }),
    )
  })
})

describe('feedback operation lifetime', () => {
  it('restores the confirmed rating when a replacement submission fails', async () => {
    const pending = deferred<MessageFeedback>()
    boundary.createFeedback.mockResolvedValueOnce(feedback(4)).mockReturnValueOnce(pending.promise)
    const view = mount()
    await rate(view.container, 4)
    await rate(view.container, 1)
    expect(view.container.textContent).toContain('1 / 5')

    await act(async () => pending.reject(new Error('submit failed')))

    expect(view.container.textContent).toContain('4 / 5')
    expect(view.container.textContent).not.toContain('主要问题')
    expect(boundary.error).toHaveBeenCalledOnce()
    expect(boundary.createFeedback.mock.calls.map(([payload]) => payload)).toEqual([
      { message_id: MESSAGE_ID, rating: 4 },
      { message_id: MESSAGE_ID, rating: 1 },
    ])
  })

  it('preserves feedback details when categorizing a low rating', async () => {
    const view = mount()
    await rate(view.container, 2)
    await act(async () => button(view.container, '答错了').click())

    expect(boundary.createFeedback).toHaveBeenLastCalledWith({
      message_id: MESSAGE_ID,
      rating: 2,
      category: 'wrong_answer',
      reason: '可复现问题',
      tags: ['review'],
      expected_answer: '正确答案',
    })
  })

  it('submits only one rating when two native clicks occur before the pending render', async () => {
    const pending = deferred<MessageFeedback>()
    boundary.createFeedback.mockReturnValue(pending.promise)
    const view = mount()

    act(() => {
      button(view.container, 'rate-2').click()
      button(view.container, 'rate-4').click()
    })

    expect(boundary.createFeedback).toHaveBeenCalledOnce()
    await act(async () => pending.resolve(feedback(2)))
  })

  it.each(['resolve', 'reject'] as const)('discards a rating %s after its message unmounts', async (settlement) => {
    const pending = deferred<MessageFeedback>()
    boundary.createFeedback.mockReturnValue(pending.promise)
    const view = mount()
    await rate(view.container, 2)
    view.unmount()

    await act(async () => {
      if (settlement === 'resolve') pending.resolve(feedback())
      else pending.reject(new Error('old request failed'))
    })

    expect(boundary.success).not.toHaveBeenCalled()
    expect(boundary.error).not.toHaveBeenCalled()
  })

  it('retires old feedback on identity change without letting its completion clear a newer submission', async () => {
    const oldRequest = deferred<MessageFeedback>()
    const currentRequest = deferred<MessageFeedback>()
    boundary.createFeedback.mockReturnValueOnce(oldRequest.promise).mockReturnValueOnce(currentRequest.promise)
    const view = mount()
    await rate(view.container, 2)

    act(() => window.dispatchEvent(new Event(AUTH_SCOPE_CHANGED_EVENT)))
    expect(view.container.textContent).not.toContain('2 / 5')
    await rate(view.container, 4)
    await act(async () => oldRequest.resolve(feedback(2)))

    expect(view.container.textContent).toContain('4 / 5')
    expect(button(view.container, 'rate-4').disabled).toBe(true)
    expect(view.container.textContent).not.toContain('feedback_id=')
    expect(boundary.success).not.toHaveBeenCalled()

    await act(async () => currentRequest.resolve({ ...feedback(4), id: 'current-feedback' }))
    expect(view.container.textContent).toContain('feedback_id=current-feedback')
    expect(button(view.container, 'rate-4').disabled).toBe(false)
  })

  it.each(['resolve', 'reject'] as const)(
    'discards a rating %s after a silent same-account login',
    async (settlement) => {
      setAuthSession({ token, user: profile })
      const pending = deferred<MessageFeedback>()
      boundary.createFeedback.mockReturnValueOnce(pending.promise).mockResolvedValueOnce(feedback(4))
      const view = mount()
      await rate(view.container, 2)
      const scopeEvent = vi.fn()
      window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, scopeEvent)
      cleanup.push(() => window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, scopeEvent))

      act(() => setAuthSession({ token, user: profile }))
      expect(scopeEvent).not.toHaveBeenCalled()
      await act(async () => {
        if (settlement === 'resolve') pending.resolve(feedback())
        else pending.reject(new Error('old login request'))
      })

      expect(boundary.success).not.toHaveBeenCalled()
      expect(boundary.error).not.toHaveBeenCalled()
      expect(view.container.textContent).not.toContain('feedback_id=')
      expect(view.container.textContent).not.toContain('2 / 5')
      expect(button(view.container, 'rate-4').disabled).toBe(false)

      await rate(view.container, 4)
      expect(view.container.textContent).toContain('4 / 5')
      expect(boundary.success).toHaveBeenCalledOnce()
    },
  )

  it('accepts a current rating after normal token rotation within its session', async () => {
    setAuthSession({ token, user: profile })
    const pending = deferred<MessageFeedback>()
    boundary.createFeedback.mockReturnValue(pending.promise)
    const view = mount()
    await rate(view.container, 2)

    act(() => setAccessToken({ ...token, access_token: 'rotated-token' }))
    await act(async () => pending.resolve(feedback()))

    expect(view.container.textContent).toContain('feedback_id=feedback-a')
    expect(boundary.success).toHaveBeenCalledOnce()
  })

  it('does not navigate when a dataset lookup resolves after leaving the message', async () => {
    const document = deferred<{ dataset_id: string }>()
    boundary.getDocument.mockReturnValue(document.promise)
    const view = mount(assistant({ citations: [citation()] }))
    await rate(view.container, 2)
    await act(async () => button(view.container, '送入证据库').click())
    expect(boundary.getDocument).toHaveBeenCalledWith('document-a', { includeChunks: false })
    view.unmount()

    await act(async () => document.resolve({ dataset_id: 'dataset-a' }))

    expect(boundary.push).not.toHaveBeenCalled()
  })

  it('retains the original dataset route and regression conversion payload for current actions', async () => {
    const view = mount(assistant({ message_metadata: { dataset_id: 'dataset/a' } }))
    await rate(view.container, 2)
    await act(async () => button(view.container, '送入证据库').click())
    expect(boundary.push).toHaveBeenCalledWith('/datasets/dataset%2Fa/evidence?feedback_id=feedback-a')

    await act(async () => button(view.container, '转为回归用例').click())
    expect(boundary.toRegressionCase).toHaveBeenCalledWith('feedback-a', {
      include_document_scope: true,
      extra: { source: 'chat_feedback_action' },
    })
  })

  it('starts only one expert action when two native clicks occur before the pending render', async () => {
    const pending = deferred<void>()
    boundary.toRegressionCase.mockReturnValue(pending.promise)
    const view = mount(assistant({ message_metadata: { dataset_id: 'dataset-a' } }))
    await rate(view.container, 2)

    act(() => {
      button(view.container, '转为回归用例').click()
      button(view.container, '送入证据库').click()
    })

    expect(boundary.toRegressionCase).toHaveBeenCalledOnce()
    expect(boundary.push).not.toHaveBeenCalled()
    await act(async () => pending.resolve())
  })

  it('discards regression success after leaving the message', async () => {
    const pending = deferred<void>()
    boundary.toRegressionCase.mockReturnValue(pending.promise)
    const view = mount()
    await rate(view.container, 2)
    boundary.success.mockClear()
    await act(async () => button(view.container, '转为回归用例').click())
    view.unmount()

    await act(async () => pending.resolve())

    expect(boundary.success).not.toHaveBeenCalled()
    expect(boundary.error).not.toHaveBeenCalled()
  })

  it('keeps transient and user messages outside the persisted assistant rating boundary', () => {
    const transient = mount(assistant({ id: 'streaming' }))
    const user = mount(assistant({ role: 'user' }))

    expect(transient.container.querySelector('[aria-label="rate-1"]')).toBeNull()
    expect(user.container.querySelector('[aria-label="rate-1"]')).toBeNull()
    expect(boundary.createFeedback).not.toHaveBeenCalled()
  })
})
