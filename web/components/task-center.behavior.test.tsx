// @vitest-environment jsdom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const documentApiMock = vi.hoisted(() => ({
  list: vi.fn(),
  cancel: vi.fn(),
  retry: vi.fn(),
}))
const authState = vi.hoisted(() => ({
  isAuthenticated: true,
}))
const backendMetaState = vi.hoisted(() => ({
  authMode: 'jwt',
}))
const routeState = vi.hoisted(() => ({
  pathname: '/knowledge/ingestion',
}))

vi.mock('@/lib/api', () => ({
  documentApi: documentApiMock,
}))
vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({
    isAuthenticated: authState.isAuthenticated,
  }),
}))
vi.mock('@/hooks/use-backend-meta', () => ({
  useBackendMeta: () => ({
    data:
      backendMetaState.authMode
        ? { features: { auth_mode: backendMetaState.authMode } }
        : undefined,
  }),
}))
vi.mock('@/i18n/navigation', () => ({
  usePathname: () => routeState.pathname,
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))
vi.mock('./ui/button', () => ({
  Button: ({
    children,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button {...props}>{children}</button>,
}))
vi.mock('./ui/scroll-area', () => ({
  ScrollArea: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div {...props}>{children}</div>
  ),
}))
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

import { TaskCenter } from './task-center'

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  return function Wrapper({
    children,
  }: Readonly<{ children: React.ReactNode }>) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
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
      </Wrapper>
    )
  })

  return { container, root }
}

describe('TaskCenter auth and polling gates', () => {
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    authState.isAuthenticated = true
    backendMetaState.authMode = 'jwt'
    routeState.pathname = '/knowledge/ingestion'
    documentApiMock.list.mockReset()
    documentApiMock.cancel.mockReset()
    documentApiMock.retry.mockReset()
    documentApiMock.list.mockResolvedValue({ items: [] })
  })

  afterEach(() => {
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

  it('stays idle on unrelated routes until the panel is explicitly opened', async () => {
    routeState.pathname = '/'

    const { root } = renderTaskCenter()
    await act(async () => {
      await Promise.resolve()
    })

    expect(documentApiMock.list).not.toHaveBeenCalled()
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
        expect(documentApiMock.list).toHaveBeenCalledTimes(1)
        expect(container.textContent).toContain('1')
      })
    })

    act(() => root.unmount())
  })

  it('loads tasks on ingestion routes for authenticated users', async () => {
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
        expect(documentApiMock.list).toHaveBeenCalledTimes(1)
        expect(container.textContent).toContain('1')
      })
    })

    act(() => root.unmount())
  })
})
