// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const boundary = vi.hoisted(() => ({
  admin: true,
  state: {} as Record<string, unknown>,
  refresh: vi.fn(),
  save: vi.fn(),
}))
vi.mock('./use-settings-page-state', () => ({ useSettingsPageState: () => boundary.state }))
vi.mock('@/hooks/use-tenant-access', () => ({
  useTenantAccess: () => ({ data: { is_active: true, role: boundary.admin ? 'owner' : 'member', permissions: [] } }),
}))
vi.mock('@/contexts/parser-backend-context', () => ({
  useParserBackendPreference: () => ({ parserBackend: 'auto', setParserBackend: vi.fn() }),
}))
vi.mock('@/contexts/chunk-strategy-context', () => ({
  useChunkStrategyPreference: () => ({ chunkStrategy: 'recursive', setChunkStrategy: vi.fn() }),
}))
vi.mock('@/components/auth/tenant-permission-gate', () => ({
  TenantPermissionGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('@/components/app-frame', () => ({
  AppFrame: ({ children }: { children: React.ReactNode }) => (
    <div id="main-content">
      <div data-page-scroll-container>{children}</div>
    </div>
  ),
}))
vi.mock('@/components/ui/page-scaffold', () => ({
  PageScaffold: ({
    actions,
    top,
    children,
  }: {
    actions: React.ReactNode
    top: React.ReactNode
    children: React.ReactNode
  }) => (
    <>
      {actions}
      {top}
      {children}
    </>
  ),
}))
vi.mock('@/components/model-config-dialog', () => ({ ModelConfigDialog: () => null }))
vi.mock('./_sections/system-status-section', () => ({ SystemStatusSection: () => null }))
vi.mock('./_sections/model-providers-section', () => ({ ModelProvidersSection: () => null }))
vi.mock('./_sections/feature-flags-section', () => ({ FeatureFlagsSection: () => null }))
vi.mock('./_sections/frontend-preferences-section', () => ({ FrontendPreferencesSection: () => null }))
vi.mock('./_sections/navigation-visibility-section', () => ({ NavigationVisibilitySection: () => null }))
vi.mock('./_sections/parser-services-section', () => ({ ParserServicesSection: () => null }))
vi.mock('./_sections/object-storage-section', () => ({ ObjectStorageSection: () => null }))
vi.mock('./_sections/rag-section', () => ({ RagSection: () => null }))
vi.mock('./_sections/ltr-model-registry-section', () => ({ LtrModelRegistrySection: () => null }))
vi.mock('./_sections/dify-integration-section', () => ({ DifyIntegrationSection: () => null }))
vi.mock('./_sections/url-ingest-section', () => ({ UrlIngestSection: () => null }))
vi.mock('./_sections/governance-section', () => ({ GovernanceSection: () => null }))
vi.mock('./_sections/industry-rules-section', () => ({ IndustryRulesSection: () => null }))
vi.mock('./_sections/observability-section', () => ({ ObservabilitySection: () => null }))
vi.mock('./_sections/runtime-controls-section', () => ({ RuntimeControlsSection: () => null }))

import SettingsPage from './page'

const cleanup: Array<() => void> = []
const observers: Array<{
  callback: IntersectionObserverCallback
  observe: ReturnType<typeof vi.fn>
  disconnect: ReturnType<typeof vi.fn>
}> = []

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

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
  observers.splice(0)
  boundary.admin = true
  boundary.state = {
    loading: false,
    loadError: null,
    saving: false,
    saveMessage: null,
    lastUpdatedKeys: [],
    hasChanges: false,
    status: null,
    groupedProviders: {},
    ragMerged: { bm25_index_enabled: false },
    getFeatureValue: () => false,
    refreshAll: boundary.refresh,
    saveSettings: boundary.save,
  }
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      observe = vi.fn()
      disconnect = vi.fn()
      constructor(callback: IntersectionObserverCallback) {
        observers.push({ callback, observe: this.observe, disconnect: this.disconnect })
      }
    },
  )
})

afterEach(() => {
  cleanup
    .splice(0)
    .reverse()
    .forEach((dispose) => dispose())
  vi.unstubAllGlobals()
})

it('keeps the section observer during normal save-state renders and releases it on unmount', () => {
  const view = mount()
  expect(observers).toHaveLength(1)
  expect(observers[0].observe).toHaveBeenCalledTimes(15)
  boundary.state = { ...boundary.state, hasChanges: true }
  view.render()
  expect(observers).toHaveLength(1)
  expect(observers[0].disconnect).not.toHaveBeenCalled()
  cleanup.pop()!()
  expect(observers[0].disconnect).toHaveBeenCalledOnce()
})

it('rebuilds observation for actual permission changes while preserving section order and hiding admin entries', () => {
  const view = mount()
  boundary.admin = false
  view.render()
  expect(observers).toHaveLength(2)
  expect(observers[0].disconnect).toHaveBeenCalledOnce()
  expect(observers[1].observe).toHaveBeenCalledTimes(10)
  expect([...view.container.querySelectorAll('nav button')].map((button) => button.textContent)).toEqual([
    '系统状态',
    '模型接入',
    '功能开关',
    '前端偏好',
    '高级解析',
    'RAG 配置',
    'LTR 模型',
    '数据治理',
    '行业规则',
    '运行控制',
  ])
  expect(view.container.querySelector('#sec-navigation')).toBeNull()
  expect(view.container.querySelector('#sec-observability')).toBeNull()
})

it('scrolls the page body using the existing index geometry and leaves the shell at the top', () => {
  const view = mount()
  const shell = view.container.querySelector<HTMLElement>('#main-content')!,
    body = view.container.querySelector<HTMLElement>('[data-page-scroll-container]')!,
    section = view.container.querySelector<HTMLElement>('#sec-rag')!
  const shellScroll = vi.fn(),
    bodyScroll = vi.fn()
  shell.scrollTo = shellScroll
  body.scrollTo = bodyScroll
  body.scrollTop = 40
  body.getBoundingClientRect = () => ({ top: 100 }) as DOMRect
  section.getBoundingClientRect = () => ({ top: 500 }) as DOMRect
  const target = [...view.container.querySelectorAll<HTMLButtonElement>('nav button')].find(
    (button) => button.textContent === 'RAG 配置',
  )!
  act(() => target.click())
  expect(shellScroll).toHaveBeenCalledWith({ top: 0, left: 0, behavior: 'auto' })
  expect(bodyScroll).toHaveBeenCalledWith({ top: 432, behavior: 'smooth' })
})

it('retains save disabled/pending and actual feedback protocols', () => {
  const view = mount()
  const save = () =>
    [...view.container.querySelectorAll<HTMLButtonElement>('button')].find(
      (button) => button.textContent?.includes('保存配置') || button.textContent?.includes('保存中...'),
    )!
  expect(save().disabled).toBe(true)
  boundary.state = { ...boundary.state, hasChanges: true }
  view.render()
  act(() => save().click())
  expect(boundary.save).toHaveBeenCalledOnce()
  boundary.state = { ...boundary.state, saving: true, saveMessage: { type: 'error', text: 'write denied' } }
  view.render()
  expect(save().disabled).toBe(true)
  expect(view.container.textContent).toContain('write denied')
})
