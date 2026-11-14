// @vitest-environment happy-dom

import React, { act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const boundary = vi.hoisted(() => ({ admin: true, state: {} as Record<string, unknown>, retry: vi.fn() }))
vi.mock('./use-settings-page-state', () => ({ useSettingsPageState: () => boundary.state }))
vi.mock('@/hooks/use-tenant-access', () => ({
  useTenantAccess: () => ({ data: { is_active: true, role: boundary.admin ? 'owner' : 'member', permissions: [] } }),
}))
vi.mock('@/hooks/use-auth', () => ({ useAuth: () => ({ isDevMode: false, user: { username: 'Current' } }) }))
vi.mock('@/i18n/navigation', () => ({
  Link: ({ href, children, ...props }: React.ComponentProps<'a'>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))
vi.mock('@/contexts/parser-backend-context', () => ({
  useParserBackendPreference: () => ({ parserBackend: 'auto', setParserBackend: vi.fn() }),
}))
vi.mock('@/contexts/chunk-strategy-context', () => ({
  useChunkStrategyPreference: () => ({ chunkStrategy: 'recursive', setChunkStrategy: vi.fn() }),
}))
vi.mock('@/components/auth/tenant-permission-gate', () => ({
  TenantPermissionGate: ({ children }: React.PropsWithChildren) => <>{children}</>,
}))
vi.mock('@/components/app-frame', () => ({
  AppFrame: ({ children }: React.PropsWithChildren) => <main>{children}</main>,
}))
vi.mock('@/components/model-config-dialog', () => ({ ModelConfigDialog: () => null }))
vi.mock('@/components/feedback-toast', () => ({
  FeedbackToast: ({ message }: { message: string | null }) => (message ? <p role="alert">{message}</p> : null),
}))
vi.mock('./_sections/system-status-section', () => ({ SystemStatusSection: () => null }))
vi.mock('./_sections/model-providers-section', () => ({ ModelProvidersSection: () => null }))
vi.mock('./_sections/feature-flags-section', () => ({ FeatureFlagsSection: () => null }))
vi.mock('./_sections/frontend-preferences-section', () => ({
  FrontendPreferencesSection: function Preferences() {
    const [value, setValue] = useState('')
    return <input aria-label="处理草稿" value={value} onChange={(event) => setValue(event.target.value)} />
  },
}))
vi.mock('./_sections/navigation-visibility-section', () => ({ NavigationVisibilitySection: () => null }))
vi.mock('./_sections/parser-services-section', () => ({ ParserServicesSection: () => null }))
vi.mock('./_sections/rag-section', () => ({ RagSection: () => null }))
vi.mock('./_sections/dify-integration-section', () => ({ DifyIntegrationSection: () => null }))
vi.mock('./_sections/governance-section', () => ({ GovernanceSection: () => null }))
vi.mock('./_sections/industry-rules-section', () => ({ IndustryRulesSection: () => null }))
vi.mock('./_sections/observability-section', () => ({ ObservabilitySection: () => null }))
vi.mock('./_sections/runtime-controls-section', () => ({ RuntimeControlsSection: () => null }))

import SettingsPage from './page'

const cleanup: Array<() => void> = []
function mount() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const render = () => act(() => root.render(<SettingsPage />))
  render()
  cleanup.push(() => {
    act(() => root.unmount())
    container.remove()
  })
  return { container, render }
}
function select(container: HTMLElement, label: string) {
  const button = [...container.querySelectorAll<HTMLButtonElement>('nav[aria-label="设置分区"] button')].find(
    (item) => item.textContent === label,
  )
  expect(button).toBeDefined()
  act(() => button!.click())
}
beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
  window.history.replaceState({}, '', '/settings')
  boundary.admin = true
  boundary.state = {
    loading: false,
    loadError: null,
    saving: false,
    saveError: null,
    hasChanges: false,
    status: null,
    groupedProviders: {},
    ragMerged: { bm25_index_enabled: false },
    getFeatureValue: () => false,
    retrySave: boundary.retry,
  }
})
afterEach(() => {
  for (const dispose of cleanup.splice(0)) dispose()
})

it('keeps one selected workspace visible and preserves inactive editor drafts', () => {
  const view = mount()
  const field = view.container.querySelector<HTMLInputElement>('[aria-label="处理草稿"]')!
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(field, 'retained')
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
  select(view.container, '检索与生成')
  expect(view.container.querySelector('#sec-frontend')?.hasAttribute('hidden')).toBe(true)
  expect(view.container.querySelector('#sec-rag')?.hasAttribute('hidden')).toBe(false)
  expect(view.container.querySelectorAll('section:not([hidden])')).toHaveLength(1)
  select(view.container, '处理偏好')
  expect(view.container.querySelector('[aria-label="处理草稿"]')).toBe(field)
  expect(field.value).toBe('retained')
})
it('updates the actual directory for permission changes without exposing admin sections', () => {
  const view = mount()
  boundary.admin = false
  view.render()
  expect(
    [...view.container.querySelectorAll('nav[aria-label="设置分区"] button')].map((item) => item.textContent),
  ).toEqual([
    '系统状态',
    '模型接入',
    '功能开关',
    '处理偏好',
    '解析服务',
    '检索与生成',
    '数据治理',
    '行业规则',
    '运行控制',
  ])
  expect(view.container.querySelector('#sec-navigation')).toBeNull()
  expect(view.container.querySelector('#sec-dify')).toBeNull()
  expect(view.container.querySelector('#sec-observability')).toBeNull()
})
it('resets the selected workspace scroll and restores an explicit section hash', () => {
  const view = mount()
  const scroll = view.container.querySelector<HTMLElement>('[data-page-scroll-container]')!
  const scrollTo = vi.fn()
  scroll.scrollTo = scrollTo
  select(view.container, '检索与生成')
  expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'auto' })
  expect(window.location.hash).toBe('#sec-rag')
  act(() => {
    window.history.replaceState({}, '', '/settings#sec-frontend')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
  expect(view.container.querySelector('#sec-frontend')?.hasAttribute('hidden')).toBe(false)
})
it('keeps save feedback local, retains the mounted editor and retries the failed draft', () => {
  const view = mount()
  const field = view.container.querySelector('[aria-label="处理草稿"]')
  boundary.state = { ...boundary.state, saving: true, hasChanges: true }
  view.render()
  expect(view.container.textContent).toContain('正在保存')
  expect(view.container.querySelector('[aria-label="处理草稿"]')).toBe(field)
  boundary.state = { ...boundary.state, saving: false, saveError: 'write denied' }
  view.render()
  expect(view.container.querySelector('[role="alert"]')?.textContent).toContain('write denied')
  const retry = [...view.container.querySelectorAll('button')].find((item) => item.textContent === '重试保存')!
  act(() => retry.click())
  expect(boundary.retry).toHaveBeenCalledOnce()
  expect([...view.container.querySelectorAll('button')].some((item) => item.textContent === '保存配置')).toBe(false)
})
