// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
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

const messages: Record<string, string | ((values?: Record<string, unknown>) => string)> = {
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
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; prefetch?: boolean }) =>
    React.createElement('a', { href, ...props }, children),
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

vi.mock('@/store/command-menu', () => ({
  useCommandMenuState: (selector: (state: typeof commandMenuStore) => unknown) => selector(commandMenuStore),
}))

vi.mock('@/components/mode-toggle', () => ({
  ModeToggle: () => React.createElement('div', { 'data-testid': 'mode-toggle' }),
}))

vi.mock('@/components/ui/status-badge', () => ({
  StatusBadge: ({ label }: { label: string }) => React.createElement('div', null, label),
}))

vi.mock('@/components/ui/popover', () => ({
  Popover: ({ children }: { children: React.ReactNode }) => React.createElement(React.Fragment, null, children),
  PopoverContent: ({ children }: { children: React.ReactNode }) => React.createElement('div', null, children),
  PopoverTrigger: ({ children }: { children: React.ReactNode }) => React.createElement(React.Fragment, null, children),
}))

import { Navbar } from './navbar'

function renderComponent(element: React.ReactElement) {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

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

  it('marks only the analysis section as current on the RAG visualization route', () => {
    const view = renderComponent(React.createElement(Navbar))

    const knowledgeSection = view.container.querySelector('button[aria-controls="sidebar-section-knowledge"]')
    const analysisSection = view.container.querySelector('button[aria-controls="sidebar-section-analysis"]')
    const knowledgeBaseLink = Array.from(view.container.querySelectorAll('a')).find(
      (node) => node.textContent?.includes('items.knowledgeBase')
    )
    const ragVisualizationLink = Array.from(view.container.querySelectorAll('a')).find(
      (node) => node.textContent?.includes('items.ragVisualization')
    )

    expect(knowledgeSection?.textContent).not.toContain('sections.current')
    expect(analysisSection?.textContent).toContain('sections.current')
    expect(knowledgeBaseLink?.getAttribute('aria-current')).toBeNull()
    expect(ragVisualizationLink?.getAttribute('aria-current')).toBe('page')

    view.unmount()
  })
})
