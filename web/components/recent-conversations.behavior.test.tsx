// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ pathname: '/datasets', search: '', query: vi.fn() }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: (options: { enabled: boolean }) => {
    state.query(options)
    return {
      data: { items: [{ id: 'thread-1', title: '维护周期' }] },
      isSuccess: true,
      isLoading: false,
      isError: false,
    }
  },
}))
vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams(state.search) }))
vi.mock('@/i18n/navigation', () => ({
  usePathname: () => state.pathname,
  Link: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}))
vi.mock('@/lib/api/chat', () => ({ chatApi: { listConversations: vi.fn() } }))
import { RecentConversations } from './recent-conversations'

let root: ReturnType<typeof createRoot> | undefined
afterEach(() => {
  if (root) act(() => root!.unmount())
  root = undefined
  document.body.innerHTML = ''
  state.pathname = '/datasets'
  state.search = ''
  state.query.mockClear()
})
function render() {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => root!.render(<RecentConversations enabled onNavigate={() => {}} />))
  return container
}
describe('recent conversation disclosure', () => {
  it('keeps the list and its request quiet until expanded, retaining the destination when opened', () => {
    const container = render()
    expect(container.querySelector('a[href="/?conversation=thread-1"]')).toBeNull()
    expect(state.query.mock.lastCall?.[0].enabled).toBe(false)
    const toggle = container.querySelector('button[aria-expanded]') as HTMLButtonElement
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    act(() => toggle.click())
    expect(container.querySelector('a[href="/?conversation=thread-1"]')?.textContent).toBe('维护周期')
    expect(state.query.mock.lastCall?.[0].enabled).toBe(true)
    act(() => toggle.click())
    expect(container.querySelector('a[href="/?conversation=thread-1"]')).toBeNull()
    expect(state.query.mock.lastCall?.[0].enabled).toBe(false)
  })
  it('keeps the active conversation discoverable', () => {
    state.pathname = '/'
    state.search = 'conversation=thread-1'
    const container = render()
    expect(container.querySelector('a[href="/?conversation=thread-1"]')).not.toBeNull()
    expect(state.query.mock.lastCall?.[0].enabled).toBe(true)
  })
  it('opens the current conversation when a new chat updates the URL in the same mounted page', () => {
    state.pathname = '/'
    const container = render()
    expect(container.querySelector('a[href="/?conversation=thread-1"]')).toBeNull()
    state.search = 'conversation=thread-1'
    act(() => root!.render(<RecentConversations enabled onNavigate={() => {}} />))
    expect(container.querySelector('a[href="/?conversation=thread-1"]')).not.toBeNull()
    expect(state.query.mock.lastCall?.[0].enabled).toBe(true)
    const toggle = container.querySelector('button[aria-expanded]') as HTMLButtonElement
    act(() => toggle.click())
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
  })
})
