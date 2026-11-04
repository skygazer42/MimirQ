// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { globalEventBus } from '@/lib/event-bus'
import { waitForAssertion } from '@/test/hook-harness'

const api = vi.hoisted(() => ({
  datasetApi: { listAll: vi.fn() },
  settingsApi: { get: vi.fn() },
  promptTemplateApi: { list: vi.fn() },
  chatApi: { streamChat: vi.fn(), chat: vi.fn(), getMessages: vi.fn() },
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api', () => api)
vi.mock('@/lib/api/datasets', () => ({ datasetApi: api.datasetApi }))
vi.mock('@/lib/api/settings', () => ({ settingsApi: api.settingsApi }))
vi.mock('@/lib/api/prompts', () => ({ promptTemplateApi: api.promptTemplateApi }))
vi.mock('@/lib/api/chat', () => ({ chatApi: api.chatApi }))
vi.mock('@/store/document-view', () => ({
  useDocumentView: (select: (state: { documentId: string | null }) => unknown) => select({ documentId: null }),
}))
vi.mock('@/components/chat/message-item', () => ({
  ChatMessageItem: ({ message }: { message: { content: string } }) => <article>{message.content}</article>,
}))
vi.mock('@/components/ui/magnetic', () => ({ Magnetic: ({ children }: { children: React.ReactNode }) => children }))
vi.mock('@/components/theme-customizer', () => ({
  ThemeCustomizer: ({ trigger }: { trigger: React.ReactNode }) => trigger,
}))
vi.mock('@/components/chat/voice-mode-overlay', () => ({ VoiceModeOverlay: () => null }))
vi.mock('@/components/chat/conversation-summary-dialog', () => ({ ConversationSummaryDialog: () => null }))
vi.mock('@/components/rag-trace/rag-trace-dialog', () => ({ RagTraceDialog: () => null }))
vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn(), reportClientWarning: vi.fn() }))
vi.mock('next-intl', () => {
  const translate = Object.assign((key: string) => key, {
    rich: (key: string) => key,
    raw: () => [],
  })
  return { useTranslations: () => translate }
})
vi.mock('next/image', () => ({
  default: ({
    priority: _priority,
    unoptimized: _unoptimized,
    ...props
  }: React.ImgHTMLAttributes<HTMLImageElement> & {
    priority?: boolean
    unoptimized?: boolean
  }) => React.createElement('img', { ...props, alt: props.alt || '' }),
}))

import { ChatArea } from './chat-area'

const cleanup: Array<() => void> = []

function mount(initial: React.ComponentProps<typeof ChatArea> = { initialPrompt: 'draft' }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const render = (props = initial) =>
    act(() =>
      root.render(
        <QueryClientProvider client={client}>
          <ChatArea {...props} />
        </QueryClientProvider>,
      ),
    )
  cleanup.push(
    () => client.clear(),
    () => {
      act(() => root.unmount())
      container.remove()
    },
  )
  render()
  return { container, render }
}

function input(container: HTMLElement) {
  return container.querySelector<HTMLTextAreaElement>('#chat-composer')!
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

async function ready(container: HTMLElement) {
  await waitForAssertion(() => {
    expect(container.querySelector<HTMLButtonElement>('button[aria-label="send"]')?.disabled).toBe(false)
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
  api.datasetApi.listAll.mockResolvedValue([{ id: 'dataset-a', name: 'Dataset A' }])
  api.promptTemplateApi.list.mockResolvedValue({ total: 0, items: [] })
  api.settingsApi.get.mockResolvedValue({ rag: { retrieval_top_k: 5, similarity_threshold: 0.7 } })
  api.chatApi.streamChat.mockImplementation(async (_request, onJson) => {
    onJson(JSON.stringify({ type: 'token', data: { content: 'answer' } }))
    onJson(
      JSON.stringify({
        type: 'done',
        data: { assistant_message_id: `assistant-${api.chatApi.streamChat.mock.calls.length}` },
      }),
    )
  })
  vi.spyOn(HTMLElement.prototype, 'scrollIntoView').mockImplementation(() => undefined)
})

afterEach(() => {
  for (const dispose of cleanup.splice(0).reverse()) dispose()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

describe('ChatArea composer intent', () => {
  it.each([{ isComposing: true }, { keyCode: 229 }])(
    'keeps the draft when Enter is part of composition: %j',
    async (composition) => {
      const view = mount()
      await ready(view.container)

      await act(async () =>
        input(view.container).dispatchEvent(
          new KeyboardEvent('keydown', {
            key: 'Enter',
            bubbles: true,
            cancelable: true,
            ...composition,
          }),
        ),
      )

      expect(api.chatApi.streamChat).not.toHaveBeenCalled()
      expect(input(view.container).value).toBe('draft')
    },
  )

  it('keeps Shift+Enter for a newline and sends normal Enter once', async () => {
    const view = mount()
    await ready(view.container)
    act(() =>
      input(view.container).dispatchEvent(
        new KeyboardEvent('keydown', {
          key: 'Enter',
          shiftKey: true,
          bubbles: true,
          cancelable: true,
        }),
      ),
    )
    expect(api.chatApi.streamChat).not.toHaveBeenCalled()
    expect(input(view.container).value).toBe('draft')

    await act(async () =>
      input(view.container).dispatchEvent(
        new KeyboardEvent('keydown', {
          key: 'Enter',
          bubbles: true,
          cancelable: true,
        }),
      ),
    )

    expect(api.chatApi.streamChat).toHaveBeenCalledOnce()
    expect(api.chatApi.streamChat.mock.calls[0]?.[0]).toMatchObject({ message: 'draft', dataset_id: 'dataset-a' })
    expect(input(view.container).value).toBe('')
  })

  it('keeps an unrelated composer draft when a follow-up question is submitted', async () => {
    const view = mount({ initialPrompt: 'my unfinished draft' })
    await ready(view.container)

    await act(async () => {
      globalEventBus.emit('chat:submit', 'follow-up question')
    })

    expect(api.chatApi.streamChat.mock.calls[0]?.[0]).toMatchObject({ message: 'follow-up question' })
    expect(input(view.container).value).toBe('my unfinished draft')
  })

  it('accepts a new autorun prompt after the first prompt was consumed', async () => {
    const consumed = vi.fn()
    const view = mount({ initialPrompt: 'first question', initialAutoSendPrompt: true, onPromptConsumed: consumed })
    await waitForAssertion(() => expect(api.chatApi.streamChat).toHaveBeenCalledTimes(1))
    await waitForAssertion(() => expect(view.container.querySelector('button[aria-label="send"]')).not.toBeNull())

    await act(async () => {
      view.render({ initialPrompt: 'second question', initialAutoSendPrompt: true, onPromptConsumed: consumed })
    })

    await waitForAssertion(() => expect(api.chatApi.streamChat).toHaveBeenCalledTimes(2))
    await waitForAssertion(() => expect(view.container.querySelector('button[aria-label="send"]')).not.toBeNull())
    expect(api.chatApi.streamChat.mock.calls.map(([request]) => request.message)).toEqual([
      'first question',
      'second question',
    ])
    expect(consumed).toHaveBeenCalledTimes(2)
  })

  it('does not replace typed input when an initial prompt arrives later', async () => {
    const view = mount({})
    await waitForAssertion(() => expect(api.datasetApi.listAll).toHaveBeenCalledOnce())
    act(() => {
      globalEventBus.emit('chat:send', 'typed draft')
    })

    view.render({ initialPrompt: 'suggested prompt' })

    expect(input(view.container).value).toBe('typed draft')
    expect(api.chatApi.streamChat).not.toHaveBeenCalled()
  })

  it('keeps an explicit retrieval setting when system defaults finish loading later', async () => {
    const settings = deferred<{ rag: { retrieval_top_k: number; similarity_threshold: number } }>()
    api.settingsApi.get.mockReturnValue(settings.promise)
    const view = mount({ initialPrompt: 'draft', initialOpenRagSettings: true })
    await ready(view.container)
    const topK = document.querySelector<HTMLInputElement>('input[type="number"]')!
    expect(topK).not.toBeNull()
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    for (const value of ['6', '5']) {
      act(() => {
        setter.call(topK, value)
        topK.dispatchEvent(new Event('input', { bubbles: true }))
      })
    }

    await act(async () => {
      settings.resolve({ rag: { retrieval_top_k: 20, similarity_threshold: 0.9 } })
      await settings.promise
      await new Promise((resolve) => globalThis.setTimeout(resolve, 0))
    })

    expect(topK.value).toBe('5')
  })

  it('retains a draft while autorun waits for scope, then sends the prompt once', async () => {
    const datasets = deferred<Array<{ id: string; name: string }>>()
    api.datasetApi.listAll.mockReturnValue(datasets.promise)
    const view = mount({ initialPrompt: 'autorun question', initialAutoSendPrompt: true })
    act(() => {
      globalEventBus.emit('chat:send', 'my new draft')
    })
    expect(api.chatApi.streamChat).not.toHaveBeenCalled()

    await act(async () => {
      datasets.resolve([{ id: 'dataset-a', name: 'Dataset A' }])
      await datasets.promise
    })
    await waitForAssertion(() => expect(api.chatApi.streamChat).toHaveBeenCalledOnce())

    expect(input(view.container).value).toBe('my new draft')
    await act(async () => {
      view.render({ initialPrompt: 'autorun question', initialAutoSendPrompt: true })
    })
    expect(api.chatApi.streamChat).toHaveBeenCalledOnce()
  })

  it('keeps a draft when no document or dataset scope is available', async () => {
    api.datasetApi.listAll.mockResolvedValue([])
    const view = mount()
    await waitForAssertion(() => expect(api.datasetApi.listAll).toHaveBeenCalledOnce())

    await act(async () =>
      input(view.container).dispatchEvent(
        new KeyboardEvent('keydown', {
          key: 'Enter',
          bubbles: true,
          cancelable: true,
        }),
      ),
    )

    expect(api.chatApi.streamChat).not.toHaveBeenCalled()
    expect(input(view.container).value).toBe('draft')
  })

  it('keeps an invalid custom metadata filter from silently submitting without it', async () => {
    const view = mount({ initialPrompt: 'draft', initialOpenRagSettings: true })
    await ready(view.container)
    const filter = Array.from(document.querySelectorAll<HTMLElement>('[role="combobox"]')).find((node) =>
      node.textContent?.includes('metadataFilters.allChunks'),
    )!
    expect(filter).toBeDefined()
    act(() => filter.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
    await waitForAssertion(() => expect(document.querySelectorAll('[role="option"]').length).toBeGreaterThan(0))
    const custom = Array.from(document.querySelectorAll<HTMLElement>('[role="option"]')).find((node) =>
      node.textContent?.includes('metadataFilters.customJson'),
    )!
    act(() => custom.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
    const editor = document.querySelector<HTMLTextAreaElement>('textarea[placeholder="metadataFilterExampleHandbook"]')!
    expect(editor).not.toBeNull()
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(editor, '{invalid')
      editor.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await waitForAssertion(() => expect(document.body.textContent).toContain('metadataFilterInvalidJson'))

    await act(async () =>
      input(view.container).dispatchEvent(
        new KeyboardEvent('keydown', {
          key: 'Enter',
          bubbles: true,
          cancelable: true,
        }),
      ),
    )

    expect(api.chatApi.streamChat).not.toHaveBeenCalled()
    expect(input(view.container).value).toBe('draft')
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(
        editor,
        '{"file_type":{"$eq":"qa"}}',
      )
      editor.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () =>
      input(view.container).dispatchEvent(
        new KeyboardEvent('keydown', {
          key: 'Enter',
          bubbles: true,
          cancelable: true,
        }),
      ),
    )
    expect(api.chatApi.streamChat).toHaveBeenCalledOnce()
    expect(api.chatApi.streamChat.mock.calls[0]?.[0].rag_config.metadata_filter).toEqual({ file_type: { $eq: 'qa' } })
  })
})
