// @vitest-environment happy-dom

import React, { act } from 'react'
import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { queryKeys } from '@/lib/query-keys'
import { waitForAssertion } from '@/test/hook-harness'

const api = vi.hoisted(() => ({
  getConversationSummary: vi.fn(),
  updateConversationSummary: vi.fn(),
  deleteConversationSummary: vi.fn(),
}))
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock('@/lib/api', () => ({ chatApi: api }))
vi.mock('@/lib/api/chat', () => ({ chatApi: api }))
vi.mock('sonner', () => ({ toast: notices }))
vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))

import { ConversationSummaryDialog } from './conversation-summary-dialog'

const cleanup: Array<() => void> = []

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function mount(conversationId = 'conversation-a') {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: Infinity,
        staleTime: 10_000,
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
      },
    },
  })
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const onOpenChange = vi.fn()
  function render(id = conversationId, open = true) {
    act(() =>
      root.render(
        <QueryClientProvider client={client}>
          <ConversationSummaryDialog open={open} onOpenChange={onOpenChange} conversationId={id} />
        </QueryClientProvider>,
      ),
    )
  }
  cleanup.push(
    () => client.clear(),
    () => {
      act(() => root.unmount())
      container.remove()
    },
  )
  render()
  return { client, render, onOpenChange }
}

function button(text: string, scope: ParentNode = document.body) {
  const element = Array.from(scope.querySelectorAll<HTMLButtonElement>('button')).find(
    (candidate) => candidate.textContent?.trim() === text,
  )
  expect(element).toBeDefined()
  return element!
}

async function beginTwoUpdates() {
  const a = deferred<{ summary: string }>()
  const b = deferred<{ summary: string }>()
  api.updateConversationSummary.mockImplementation((id: string) => (id === 'conversation-a' ? a.promise : b.promise))
  const view = mount()
  await waitForAssertion(() => expect(document.body.textContent).toContain('summary-conversation-a'))
  act(() => button('更新').click())
  await waitForAssertion(() => expect(api.updateConversationSummary).toHaveBeenCalledWith('conversation-a'))
  view.client.setQueryData(queryKeys.chat.summary('conversation-b'), { available: true, summary: 'cached-b' })
  view.render('conversation-b')
  expect(button('更新').disabled).toBe(false)
  act(() => button('更新').click())
  await waitForAssertion(() => expect(api.updateConversationSummary).toHaveBeenCalledWith('conversation-b'))
  view.render('conversation-a')
  return { view, a, b }
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
  onlineManager.setOnline(true)
  api.getConversationSummary.mockImplementation(async (id: string) => ({ available: true, summary: `summary-${id}` }))
})

afterEach(() => {
  for (const dispose of cleanup.splice(0).reverse()) dispose()
  onlineManager.setOnline(true)
  document.body.innerHTML = ''
})

describe('ConversationSummaryDialog operation scope', () => {
  it.each(['update', 'clear'] as const)(
    'keeps the completed %s when a reconnect read started during the mutation returns late',
    async (action) => {
      const mutation = deferred<{ summary: string } | void>()
      const read = deferred<{ available: boolean; summary: string }>()
      if (action === 'update') api.updateConversationSummary.mockReturnValue(mutation.promise)
      else api.deleteConversationSummary.mockReturnValue(mutation.promise)
      const view = mount()
      const key = queryKeys.chat.summary('conversation-a')
      await waitForAssertion(() => expect(document.body.textContent).toContain('summary-conversation-a'))
      if (action === 'update') act(() => button('更新').click())
      else {
        act(() => button('清空').click())
        const confirm = document.querySelector<HTMLElement>('[role="alertdialog"]')!
        act(() => button('清空', confirm).click())
      }
      await waitForAssertion(() =>
        expect(
          action === 'update' ? api.updateConversationSummary : api.deleteConversationSummary,
        ).toHaveBeenCalledOnce(),
      )
      api.getConversationSummary.mockReturnValueOnce(read.promise)
      act(() => {
        view.client.setQueryData(key, { available: true, summary: 'summary-conversation-a' }, { updatedAt: 1 })
        onlineManager.setOnline(false)
        onlineManager.setOnline(true)
      })
      await waitForAssertion(() => expect(api.getConversationSummary).toHaveBeenCalledTimes(2))
      const expected =
        action === 'update' ? { available: true, summary: 'updated-after-write' } : { available: false, summary: '' }

      await act(async () => {
        mutation.resolve(action === 'update' ? { summary: 'updated-after-write' } : undefined)
        await mutation.promise
      })
      await waitForAssertion(() => expect(view.client.getQueryData(key)).toEqual(expected))
      await act(async () => {
        read.resolve({ available: true, summary: 'stale-before-write' })
        await read.promise
        await new Promise((resolve) => globalThis.setTimeout(resolve, 0))
      })

      expect(view.client.getQueryData(key)).toEqual(expected)
      expect(document.body.textContent).not.toContain('stale-before-write')
    },
  )

  it('keeps clear confirmation open until deletion and the visible cache update finish', async () => {
    const deletion = deferred<void>()
    api.deleteConversationSummary.mockReturnValue(deletion.promise)
    const view = mount()
    await waitForAssertion(() => expect(document.body.textContent).toContain('summary-conversation-a'))
    act(() => button('清空').click())
    const confirm = document.querySelector<HTMLElement>('[role="alertdialog"]')!
    const confirmButton = button('清空', confirm)
    act(() => confirmButton.click())
    await waitForAssertion(() => expect(api.deleteConversationSummary).toHaveBeenCalledOnce())

    expect(document.querySelector('[role="alertdialog"]')).not.toBeNull()
    expect(confirmButton.disabled).toBe(true)
    expect(button('返回', confirm).disabled).toBe(true)
    await act(async () => {
      deletion.resolve()
      await deletion.promise
    })
    await waitForAssertion(() => expect(document.querySelector('[role="alertdialog"]')).toBeNull())
    expect(view.client.getQueryData(queryKeys.chat.summary('conversation-a'))).toEqual({
      available: false,
      summary: '',
    })
  })

  it('keeps a failed clear open with its error so it can be retried', async () => {
    api.deleteConversationSummary.mockRejectedValue(new Error('delete failed'))
    mount()
    await waitForAssertion(() => expect(document.body.textContent).toContain('summary-conversation-a'))
    act(() => button('清空').click())
    const confirm = document.querySelector<HTMLElement>('[role="alertdialog"]')!
    act(() => button('清空', confirm).click())

    await waitForAssertion(() => {
      const current = document.querySelector<HTMLElement>('[role="alertdialog"]')
      expect(current).not.toBeNull()
      expect(current?.textContent).toContain('delete failed')
      expect(button('清空', current!).disabled).toBe(false)
    })
    expect(document.body.textContent).toContain('summary-conversation-a')
    api.deleteConversationSummary.mockResolvedValue(undefined)
    act(() => button('清空', document.querySelector('[role="alertdialog"]')!).click())
    await waitForAssertion(() => expect(document.querySelector('[role="alertdialog"]')).toBeNull())
    expect(api.deleteConversationSummary).toHaveBeenCalledTimes(2)
  })

  it('updates the original conversation cache when the active conversation changes', async () => {
    const update = deferred<{ summary: string }>()
    api.updateConversationSummary.mockReturnValue(update.promise)
    const view = mount()
    await waitForAssertion(() => expect(document.body.textContent).toContain('summary-conversation-a'))
    act(() => button('更新').click())
    await waitForAssertion(() => expect(api.updateConversationSummary).toHaveBeenCalledOnce())
    view.render('conversation-b')
    await waitForAssertion(() => expect(document.body.textContent).toContain('summary-conversation-b'))

    await act(async () => {
      update.resolve({ summary: 'updated-a' })
      await update.promise
    })

    expect(view.client.getQueryData(queryKeys.chat.summary('conversation-a'))).toEqual({
      available: true,
      summary: 'updated-a',
    })
    expect(view.client.getQueryData(queryKeys.chat.summary('conversation-b'))).toEqual({
      available: true,
      summary: 'summary-conversation-b',
    })
    expect(notices.success).not.toHaveBeenCalled()
  })

  it('does not restore an old summary after its query cache is cleared', async () => {
    const update = deferred<{ summary: string }>()
    api.updateConversationSummary.mockReturnValue(update.promise)
    const view = mount()
    await waitForAssertion(() => expect(document.body.textContent).toContain('summary-conversation-a'))
    act(() => button('更新').click())
    await waitForAssertion(() => expect(api.updateConversationSummary).toHaveBeenCalledOnce())
    api.getConversationSummary.mockResolvedValue({ available: true, summary: 'replacement' })
    act(() => view.client.clear())
    view.render()
    await waitForAssertion(() => expect(document.body.textContent).toContain('replacement'))

    await act(async () => {
      update.resolve({ summary: 'old-private-summary' })
      await update.promise
    })

    expect(view.client.getQueryData(queryKeys.chat.summary('conversation-a'))).toEqual({
      available: true,
      summary: 'replacement',
    })
    expect(notices.success).not.toHaveBeenCalled()
  })

  it('keeps conflicting summary actions disabled while updating', async () => {
    const update = deferred<{ summary: string }>()
    api.updateConversationSummary.mockReturnValue(update.promise)
    mount()
    await waitForAssertion(() => expect(document.body.textContent).toContain('summary-conversation-a'))
    act(() => button('更新').click())
    await waitForAssertion(() => expect(button('更新').disabled).toBe(true))

    expect(button('刷新').disabled).toBe(true)
    expect(button('清空').disabled).toBe(true)
    await act(async () => {
      update.resolve({ summary: 'updated-a' })
      await update.promise
    })
  })

  it('leaves an already cached new conversation available while the old one updates', async () => {
    const update = deferred<{ summary: string }>()
    api.updateConversationSummary.mockReturnValue(update.promise)
    const view = mount()
    await waitForAssertion(() => expect(document.body.textContent).toContain('summary-conversation-a'))
    act(() => button('更新').click())
    await waitForAssertion(() => expect(button('更新').disabled).toBe(true))
    view.client.setQueryData(queryKeys.chat.summary('conversation-b'), { available: true, summary: 'cached-b' })

    view.render('conversation-b')

    expect(document.body.textContent).toContain('cached-b')
    expect(button('更新').disabled).toBe(false)
    await act(async () => {
      update.resolve({ summary: 'updated-a' })
      await update.promise
    })
  })

  it('keeps the same conversation busy after leaving and returning before its update finishes', async () => {
    const update = deferred<{ summary: string }>()
    api.updateConversationSummary.mockReturnValue(update.promise)
    const view = mount()
    await waitForAssertion(() => expect(document.body.textContent).toContain('summary-conversation-a'))
    act(() => button('更新').click())
    await waitForAssertion(() => expect(button('更新').disabled).toBe(true))
    view.client.setQueryData(queryKeys.chat.summary('conversation-b'), { available: true, summary: 'cached-b' })
    view.render('conversation-b')

    view.render('conversation-a')

    expect(button('更新').disabled).toBe(true)
    expect(button('清空').disabled).toBe(true)
    await act(async () => {
      update.resolve({ summary: 'updated-a' })
      await update.promise
    })
  })

  it('keeps A busy when returning while independent A and B updates are both pending', async () => {
    const { a, b } = await beginTwoUpdates()

    expect(button('更新').disabled).toBe(true)
    expect(button('清空').disabled).toBe(true)
    expect(button('刷新').disabled).toBe(true)
    await act(async () => a.resolve({ summary: 'updated-a' }))
    await waitForAssertion(() => expect(button('更新').disabled).toBe(false))
    await act(async () => b.resolve({ summary: 'updated-b' }))
  })

  it('blocks clearing A until its original update finishes while B can remain pending', async () => {
    const { view, a, b } = await beginTwoUpdates()
    const key = queryKeys.chat.summary('conversation-a')

    act(() => button('清空').click())
    expect(document.querySelector('[role="alertdialog"]')).toBeNull()
    expect(api.deleteConversationSummary).not.toHaveBeenCalled()
    await act(async () => a.resolve({ summary: 'old-a-before-clear' }))
    await waitForAssertion(() =>
      expect(view.client.getQueryData(key)).toEqual({ available: true, summary: 'old-a-before-clear' }),
    )
    await waitForAssertion(() => expect(view.client.isMutating()).toBe(1))
    await waitForAssertion(() => expect(button('清空').disabled).toBe(false))

    api.deleteConversationSummary.mockResolvedValue(undefined)
    act(() => button('清空').click())
    const confirm = document.querySelector<HTMLElement>('[role="alertdialog"]')!
    act(() => button('清空', confirm).click())
    await waitForAssertion(() => expect(view.client.getQueryData(key)).toEqual({ available: false, summary: '' }))
    await act(async () => b.resolve({ summary: 'late-b-after-a-clear' }))
    await waitForAssertion(() => expect(view.client.isMutating()).toBe(0))

    expect(view.client.getQueryData(key)).toEqual({ available: false, summary: '' })
    expect(api.updateConversationSummary.mock.calls).toEqual([['conversation-a'], ['conversation-b']])
    expect(api.deleteConversationSummary.mock.calls).toEqual([['conversation-a']])
  })

  it('shows a read failure distinctly from an empty summary', async () => {
    api.getConversationSummary.mockRejectedValue(new Error('read failed'))
    mount()

    await waitForAssertion(() => expect(document.querySelector('[role="alert"]')?.textContent).toContain('read failed'))
    expect(document.body.textContent).toContain('加载失败')
  })

  it('publishes the current update and retains summary request arguments', async () => {
    api.updateConversationSummary.mockResolvedValue({ summary: 'current-updated-summary' })
    const view = mount()
    await waitForAssertion(() => expect(document.body.textContent).toContain('summary-conversation-a'))

    act(() => button('更新').click())

    await waitForAssertion(() => expect(document.body.textContent).toContain('current-updated-summary'))
    expect(api.updateConversationSummary.mock.calls).toEqual([['conversation-a']])
    expect(view.client.getQueryData(queryKeys.chat.summary('conversation-a'))).toEqual({
      available: true,
      summary: 'current-updated-summary',
    })
    expect(notices.success).toHaveBeenCalledWith('摘要已更新')
  })

  it('keeps the no-conversation state free of summary requests', () => {
    mount('')

    expect(document.body.textContent).toContain('当前还没有会话 ID')
    expect(api.getConversationSummary).not.toHaveBeenCalled()
    expect(api.updateConversationSummary).not.toHaveBeenCalled()
    expect(api.deleteConversationSummary).not.toHaveBeenCalled()
  })
})
