// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { AUTH_SCOPE_CHANGED_EVENT } from '@/lib/auth-storage'

const documentApiMock = vi.hoisted(() => ({
  list: vi.fn(),
  cancel: vi.fn(),
  retry: vi.fn(),
}))
const authState = vi.hoisted(() => ({
  isAuthenticated: true,
  revision: 0,
}))
const backendMetaState = vi.hoisted(() => ({
  authMode: 'jwt',
}))
const routeState = vi.hoisted(() => ({
  pathname: '/knowledge/ingestion',
}))

vi.mock('@/lib/api/documents', () => ({
  documentApi: {
    ...documentApiMock,
    list: async (params: { status: string }) => {
      const response: { items: { status: string }[] } = await documentApiMock.list(params)
      const items = response.items.filter(
        (item) => item.status === params.status || (params.status === 'processing' && item.status === 'pending'),
      )
      return { items, total: items.length }
    },
  },
}))
vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({
    isAuthenticated: authState.isAuthenticated,
  }),
}))
vi.mock('@/lib/auth-storage', () => ({
  AUTH_SCOPE_CHANGED_EVENT: 'mimirq:auth-scope-changed',
  getAuthSessionRevision: () => authState.revision,
  getAccessToken: () => (authState.isAuthenticated ? 'controlled-access-token' : null),
}))
vi.mock('@/hooks/use-backend-meta', () => ({
  useBackendMeta: () => ({
    data: backendMetaState.authMode ? { features: { auth_mode: backendMetaState.authMode } } : undefined,
    isPending: false,
    isError: false,
  }),
}))
vi.mock('@/i18n/navigation', () => ({
  usePathname: () => routeState.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))
vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))
vi.mock('./ui/button', () => ({
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props}>{children}</button>
  ),
}))
vi.mock('./ui/scroll-area', () => ({
  ScrollArea: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => <div {...props}>{children}</div>,
}))
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

import { TaskCenter } from './task-center'
import { AuthGuard } from './auth-guard'
import { QueryProvider } from './providers/query-provider'

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  function Wrapper({ children }: Readonly<{ children: React.ReactNode }>) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }

  return Wrapper
}

function renderTaskCenter() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const Wrapper = createWrapper()

  act(() => {
    root.render(
      <Wrapper>
        <TaskCenter />
      </Wrapper>,
    )
  })

  return { container, root }
}

function deferredAction() {
  let resolve!: () => void
  let reject!: (error: Error) => void
  const promise = new Promise<void>((fulfill, fail) => {
    resolve = fulfill
    reject = fail
  })
  return { promise, resolve, reject }
}

describe('TaskCenter auth and polling gates', () => {
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    authState.isAuthenticated = true
    authState.revision = 0
    backendMetaState.authMode = 'jwt'
    routeState.pathname = '/knowledge/ingestion'
    documentApiMock.list.mockReset()
    documentApiMock.cancel.mockReset()
    documentApiMock.retry.mockReset()
    documentApiMock.list.mockResolvedValue({ items: [] })
  })

  afterEach(() => {
    vi.useRealTimers()
    document.body.innerHTML = ''
    vi.clearAllMocks()
  })

  it('does not request tasks for jwt mode without a token', async () => {
    authState.isAuthenticated = false

    const { container, root } = renderTaskCenter()
    await act(async () => {
      await Promise.resolve()
    })

    expect(documentApiMock.list).not.toHaveBeenCalled()
    expect(container.textContent).toBe('')
    act(() => root.unmount())
  })

  it('does not request tasks on auth subroutes even when header auth would otherwise allow loading', async () => {
    authState.isAuthenticated = false
    backendMetaState.authMode = 'header'
    routeState.pathname = '/auth/saml/callback'

    const { container, root } = renderTaskCenter()
    await act(async () => {
      await Promise.resolve()
    })

    expect(documentApiMock.list).not.toHaveBeenCalled()
    expect(container.textContent).toBe('')
    act(() => root.unmount())
  })

  it('hides previously discovered tasks after navigating into auth routes', async () => {
    routeState.pathname = '/'
    documentApiMock.list.mockResolvedValue({
      items: [
        {
          id: 'doc-auth-hide',
          filename: 'failed.pdf',
          status: 'failed',
          error_message: 'boom',
        },
      ],
    })

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    const Wrapper = createWrapper()

    act(() => {
      root.render(
        <Wrapper>
          <TaskCenter />
        </Wrapper>,
      )
    })
    await act(async () => {
      await vi.waitFor(() => {
        expect(documentApiMock.list).toHaveBeenCalledTimes(3)
        expect(container.textContent).toContain('1')
      })
    })

    routeState.pathname = '/auth/saml/callback'
    await act(async () => {
      root.render(
        <Wrapper>
          <TaskCenter />
        </Wrapper>,
      )
      await Promise.resolve()
    })

    expect(container.textContent).toBe('')
    act(() => root.unmount())
  })

  it('discovers tasks on unrelated authenticated routes and stays on a low-frequency idle poll', async () => {
    vi.useFakeTimers()
    routeState.pathname = '/'
    documentApiMock.list.mockResolvedValue({
      items: [
        {
          id: 'doc-3',
          filename: 'failed.pdf',
          status: 'failed',
          error_message: 'boom',
        },
      ],
    })

    const { root } = renderTaskCenter()
    await act(async () => {
      await vi.waitFor(() => expect(documentApiMock.list).toHaveBeenCalledTimes(3))
    })

    await act(async () => {
      vi.advanceTimersByTime(5000)
      await Promise.resolve()
    })
    expect(documentApiMock.list).toHaveBeenCalledTimes(3)
    await act(async () => {
      vi.advanceTimersByTime(55000)
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(documentApiMock.list).toHaveBeenCalledTimes(6)
    act(() => root.unmount())
  })

  it('switches to the fast poll when an active task is present outside task routes', async () => {
    vi.useFakeTimers()
    routeState.pathname = '/'
    documentApiMock.list.mockResolvedValue({
      items: [
        {
          id: 'doc-4',
          filename: 'active.pdf',
          status: 'processing',
          processing_progress: 30,
          current_stage: 'indexing',
        },
      ],
    })

    const { container, root } = renderTaskCenter()

    await act(async () => {
      await vi.waitFor(() => {
        expect(documentApiMock.list).toHaveBeenCalledTimes(3)
        expect(container.textContent).toContain('1')
      })
    })
    await act(async () => {
      vi.advanceTimersByTime(5000)
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(documentApiMock.list).toHaveBeenCalledTimes(6)
    act(() => root.unmount())
  })

  it('loads tasks on supported header mode routes without requiring a token', async () => {
    authState.isAuthenticated = false
    backendMetaState.authMode = 'header'
    documentApiMock.list.mockResolvedValue({
      items: [
        {
          id: 'doc-2',
          filename: 'header-mode.pdf',
          status: 'processing',
          processing_progress: 30,
          current_stage: 'indexing',
        },
      ],
    })

    const { container, root } = renderTaskCenter()

    await act(async () => {
      await vi.waitFor(() => {
        expect(documentApiMock.list).toHaveBeenCalledTimes(3)
        expect(container.textContent).toContain('1')
      })
    })

    act(() => root.unmount())
  })

  it('uses the fast poll cadence on task routes for authenticated users', async () => {
    vi.useFakeTimers()
    documentApiMock.list.mockResolvedValue({
      items: [
        {
          id: 'doc-1',
          filename: 'pending.pdf',
          status: 'processing',
          processing_progress: 45,
          current_stage: 'embedding',
        },
      ],
    })

    const { container, root } = renderTaskCenter()

    await act(async () => {
      await vi.waitFor(() => {
        expect(documentApiMock.list).toHaveBeenCalledTimes(3)
        expect(container.textContent).toContain('1')
      })
    })
    await act(async () => {
      vi.advanceTimersByTime(5000)
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(documentApiMock.list).toHaveBeenCalledTimes(6)
    act(() => root.unmount())
  })

  it('uses the fast poll cadence while the panel is open', async () => {
    vi.useFakeTimers()
    routeState.pathname = '/'
    documentApiMock.list.mockResolvedValue({
      items: [
        {
          id: 'doc-5',
          filename: 'failed.pdf',
          status: 'failed',
          error_message: 'boom',
        },
      ],
    })

    const { container, root } = renderTaskCenter()

    await act(async () => {
      await vi.waitFor(() => {
        expect(documentApiMock.list).toHaveBeenCalledTimes(3)
        expect(container.querySelector('[aria-label="title"]')).not.toBeNull()
      })
    })

    const toggle = container.querySelector<HTMLButtonElement>('[aria-label="title"]')
    expect(toggle).not.toBeNull()
    act(() => toggle?.click())

    await act(async () => {
      vi.advanceTimersByTime(5000)
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(documentApiMock.list).toHaveBeenCalledTimes(6)
    act(() => root.unmount())
  })

  it.each(['cancel', 'retry'] as const)(
    'keeps a new session action pending when an old %s completes',
    async (action) => {
      const first = deferredAction()
      const second = deferredAction()
      documentApiMock[action].mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
      documentApiMock.list.mockResolvedValue({
        items: ['doc-a', 'doc-b'].map((id) => ({
          id,
          filename: id,
          status: action === 'retry' ? 'failed' : 'processing',
        })),
      })
      const { container, root } = renderTaskCenter()
      await act(async () => {
        await vi.waitFor(() => expect(container.querySelector('[aria-label="title"]')).not.toBeNull())
      })
      act(() => container.querySelector<HTMLButtonElement>('[aria-label="title"]')?.click())
      const buttons = container.querySelectorAll<HTMLButtonElement>(
        action === 'retry' ? '[aria-label="retryTask"]' : '[aria-label="cancelTask"]',
      )
      expect(buttons).toHaveLength(2)
      act(() => buttons[0].click())
      expect(buttons[0].disabled).toBe(true)
      expect(buttons[1].disabled).toBe(true)

      act(() => {
        authState.revision += 1
        window.dispatchEvent(new Event(AUTH_SCOPE_CHANGED_EVENT))
      })
      expect(buttons[0].disabled).toBe(false)
      act(() => buttons[1].click())
      expect(documentApiMock[action]).toHaveBeenCalledTimes(2)

      await act(async () => {
        first.resolve()
        await first.promise
      })

      expect(toast.success).not.toHaveBeenCalled()
      expect(documentApiMock.list).toHaveBeenCalledTimes(3)
      expect(buttons[1].disabled).toBe(true)
      await act(async () => {
        second.resolve()
        await second.promise
      })
      expect(toast.success).toHaveBeenCalledOnce()
      expect(documentApiMock.list).toHaveBeenCalledTimes(6)
      expect(buttons[1].disabled).toBe(false)
      act(() => root.unmount())
    },
  )

  it.each(['cancel', 'retry'] as const)('ignores a %s failure after unmount', async (action) => {
    const operation = deferredAction()
    documentApiMock[action].mockReturnValue(operation.promise)
    documentApiMock.list.mockResolvedValue({
      items: [{ id: 'doc-a', filename: 'doc-a', status: action === 'retry' ? 'failed' : 'processing' }],
    })
    const { container, root } = renderTaskCenter()
    await act(async () => {
      await vi.waitFor(() => expect(container.querySelector('[aria-label="title"]')).not.toBeNull())
    })
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="title"]')?.click())
    const button = container.querySelector<HTMLButtonElement>(
      action === 'retry' ? '[aria-label="retryTask"]' : '[aria-label="cancelTask"]',
    )
    expect(button).not.toBeNull()
    act(() => button?.click())
    act(() => root.unmount())

    await act(async () => {
      operation.reject(new Error('Old task failed'))
      await Promise.resolve()
    })

    expect(toast.error).not.toHaveBeenCalled()
    expect(toast.success).not.toHaveBeenCalled()
    expect(documentApiMock.list).toHaveBeenCalledTimes(3)
  })

  it('replaces idle task data when the application auth scope changes', async () => {
    backendMetaState.authMode = 'header'
    documentApiMock.list.mockImplementation(async () => ({
      items: [
        authState.revision === 0
          ? { id: 'tenant-a-document', filename: 'Tenant A task', status: 'processing' }
          : { id: 'tenant-b-document', filename: 'Tenant B task', status: 'processing' },
      ],
    }))
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    act(() => {
      root.render(
        <QueryProvider>
          <AuthGuard>
            <TaskCenter />
          </AuthGuard>
        </QueryProvider>,
      )
    })
    await act(async () => {
      await vi.waitFor(() => expect(container.querySelector('[aria-label="title"]')).not.toBeNull())
    })
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="title"]')?.click())
    expect(container.textContent).toContain('Tenant A task')

    act(() => {
      authState.revision += 1
      window.dispatchEvent(new Event(AUTH_SCOPE_CHANGED_EVENT))
    })

    expect(container.textContent).not.toContain('Tenant A task')
    await act(async () => {
      await vi.waitFor(() => {
        expect(documentApiMock.list).toHaveBeenCalledTimes(6)
        expect(container.querySelector('[aria-label="title"]')).not.toBeNull()
      })
    })
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="title"]')?.click())
    expect(container.textContent).toContain('Tenant B task')
    act(() => root.unmount())
  })
})
