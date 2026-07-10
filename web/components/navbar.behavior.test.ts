// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot, hydrateRoot } from 'react-dom/client'
import { renderToString } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const routerMocks = vi.hoisted(() => ({
  pathname: '/knowledge/similarity',
  prefetch: vi.fn(),
  push: vi.fn(),
}))

const commandMenuStore = vi.hoisted(() => ({
  open: false,
  setOpen: vi.fn(),
}))

const adminTenantAccess = {
  account_id: 'test-account',
  is_active: true,
  is_current: true,
  permissions: [
    'settings.read',
    'settings.write',
    'observability.read',
    'usage.read',
    'audit.read',
    'audit.manage',
    'table_sql.read',
    'lifecycle.manage',
  ],
  role: 'admin',
  tenant_id: 'test-tenant',
}

const tenantAccessMock = vi.hoisted(() => ({
  current: {
    data: undefined as unknown,
  },
}))

const messages: Record<
  string,
  string | ((values?: Record<string, unknown>) => string)
> = {
  'actions.newConversation': 'actions.newConversation',
  'auth.goToLogin': 'auth.goToLogin',
  'auth.login': 'auth.login',
  'brand.tagline': 'brand.tagline',
  'command.triggerHint': 'command.triggerHint',
  'command.triggerLabel': 'command.triggerLabel',
  'deps.openStatus': 'deps.openStatus',
  'deps.ready': 'deps.ready',
  'deps.unavailable': 'deps.unavailable',
  'items.ragVisualization': 'items.ragVisualization',
  'items.knowledgeBase': 'items.knowledgeBase',
  'sections.analysis': 'sections.analysis',
  'sections.core': 'sections.core',
  'sections.current': 'sections.current',
  'sections.entryCount': (values) => `count:${String(values?.count ?? '')}`,
  'sections.ingestion': 'sections.ingestion',
  'sections.knowledge': 'sections.knowledge',
  'sections.system': 'sections.system',
  'status.badgePrefix': 'status.badgePrefix:',
  'toolbar.navLabel': 'toolbar.navLabel',
  'toolbar.sidebarClose': 'toolbar.sidebarClose',
  'user.offlineEnvironment': 'user.offlineEnvironment',
  'user.openSettings': 'user.openSettings',
  'user.unauthenticatedName': 'user.unauthenticatedName',
}

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string, values?: Record<string, unknown>) => {
    const value = messages[key]
    if (typeof value === 'function') return value(values)
    return value ?? key
  },
}))

vi.mock('@/i18n/navigation', () => ({
  Link: ({
    children,
    href,
    prefetch: _prefetch,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string
    prefetch?: boolean
  }) => React.createElement('a', { href, ...props }, children),
  usePathname: () => routerMocks.pathname,
  useRouter: () => ({
    prefetch: routerMocks.prefetch,
    push: routerMocks.push,
  }),
}))

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({
    isAuthenticated: false,
    isDevMode: true,
    logout: vi.fn(),
    user: null,
  }),
}))

vi.mock('@/hooks/use-backend-meta', () => ({
  useBackendMeta: () => ({
    data: null,
  }),
}))

vi.mock('@/hooks/use-backend-ready', () => ({
  useBackendReady: () => ({
    data: null,
    dataUpdatedAt: 0,
    errorUpdatedAt: 0,
    isError: false,
  }),
}))

vi.mock('@/hooks/use-tenant-access', () => ({
  useTenantAccess: () => tenantAccessMock.current,
}))

vi.mock('@/store/command-menu', () => ({
  useCommandMenuState: (
    selector: (state: typeof commandMenuStore) => unknown
  ) => selector(commandMenuStore),
}))

vi.mock('@/components/mode-toggle', () => ({
  ModeToggle: () =>
    React.createElement('div', { 'data-testid': 'mode-toggle' }),
}))

vi.mock('@/components/ui/status-badge', () => ({
  StatusBadge: ({ label }: { label: string }) =>
    React.createElement('div', null, label),
}))

vi.mock('@/components/ui/popover', () => ({
  Popover: ({ children }: { children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children),
  PopoverContent: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', null, children),
  PopoverTrigger: ({ children }: { children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children),
}))

import { Navbar } from './navbar'

function renderComponent(element: React.ReactElement) {
  ;(
    globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }
  ).IS_REACT_ACT_ENVIRONMENT = true

  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)

  act(() => {
    root.render(element)
  })

  return {
    container,
    unmount() {
      act(() => {
        root.unmount()
      })
      container.remove()
    },
  }
}

describe('Navbar behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    routerMocks.pathname = '/knowledge/similarity'
    commandMenuStore.open = false
    commandMenuStore.setOpen = vi.fn()
    tenantAccessMock.current = { data: adminTenantAccess }
    window.localStorage.clear()
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        addEventListener: vi.fn(),
        addListener: vi.fn(),
        dispatchEvent: vi.fn(),
        matches: false,
        media: query,
        onchange: null,
        removeEventListener: vi.fn(),
        removeListener: vi.fn(),
      })),
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('keeps the advanced similarity route out of the primary sidebar', () => {
    const view = renderComponent(React.createElement(Navbar))

    const knowledgeSection = view.container.querySelector(
      'button[aria-controls="sidebar-section-knowledge"]'
    )
    const analysisSection = view.container.querySelector(
      'button[aria-controls="sidebar-section-analysis"]'
    )
    const knowledgeBaseLink = Array.from(
      view.container.querySelectorAll('a')
    ).find((node) => node.textContent?.includes('items.knowledgeBase'))
    const evaluationsLink = Array.from(view.container.querySelectorAll('a')).find(
      (node) => node.textContent?.includes('items.ragas')
    )
    const ragVisualizationLink = Array.from(view.container.querySelectorAll('a')).find(
      (node) => node.textContent?.includes('items.ragVisualization')
    )

    // After V3: "current" badge removed; verify active section is identified by expanded state
    const analysisToggle = view.container.querySelector(
      'button[aria-controls="sidebar-section-analysis"]'
    ) as HTMLButtonElement
    expect(analysisToggle?.getAttribute('aria-expanded')).toBe('true')
    expect(knowledgeBaseLink?.getAttribute('aria-current')).toBeNull()
    expect(evaluationsLink?.getAttribute('aria-current')).toBe('page')
    expect(ragVisualizationLink).toBeUndefined()

    view.unmount()
  })

  it('preserves manually collapsed sections across remounts while opening the active section', () => {
    routerMocks.pathname = '/'

    const firstView = renderComponent(React.createElement(Navbar))
    const coreToggle = firstView.container.querySelector(
      'button[aria-controls="sidebar-section-core"]'
    ) as HTMLButtonElement
    const knowledgeToggle = firstView.container.querySelector(
      'button[aria-controls="sidebar-section-knowledge"]'
    ) as HTMLButtonElement

    act(() => {
      coreToggle.click()
      knowledgeToggle.click()
    })

    firstView.unmount()

    routerMocks.pathname = '/graph'

    const secondView = renderComponent(React.createElement(Navbar))
    const coreSection = secondView.container.querySelector(
      '#sidebar-section-core'
    )
    const knowledgeSection = secondView.container.querySelector(
      '#sidebar-section-knowledge'
    )
    const analysisToggle = secondView.container.querySelector(
      'button[aria-controls="sidebar-section-analysis"]'
    ) as HTMLButtonElement
    const analysisSection = secondView.container.querySelector(
      '#sidebar-section-analysis'
    )

    // After V3: verify analysis section auto-opens for active route
    expect(analysisToggle.getAttribute('aria-expanded')).toBe('true')
    expect(analysisSection?.getAttribute('class')).toContain('grid-rows-[1fr]')

    secondView.unmount()
  })

  it('keeps permission-gated navigation stable across hydration when tenant access is client-cached', async () => {
    routerMocks.pathname = '/usage'
    tenantAccessMock.current = { data: undefined }
    const html = renderToString(React.createElement(Navbar))

    const container = document.createElement('div')
    container.innerHTML = html
    document.body.appendChild(container)
    tenantAccessMock.current = { data: adminTenantAccess }

    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    let root: ReturnType<typeof hydrateRoot> | null = null

    await act(async () => {
      root = hydrateRoot(container, React.createElement(Navbar))
      await Promise.resolve()
    })

    const errorOutput = consoleError.mock.calls.map((call) => call.join(' ')).join('\n')
    expect(errorOutput).not.toContain('Hydration failed')

    await act(async () => {
      root?.unmount()
    })
    container.remove()
  })
})
