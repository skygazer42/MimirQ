// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const authApiMock = vi.hoisted(() => ({
  login: vi.fn(),
  register: vi.fn(),
}))
const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
}))
const sessionMock = vi.hoisted(() => ({
  setAuthSession: vi.fn(),
}))

vi.mock('next/image', () => ({
  default: ({
    priority: _priority,
    unoptimized: _unoptimized,
    ...props
  }: React.ComponentProps<'img'> & { priority?: boolean; unoptimized?: boolean }) =>
    React.createElement('img', props),
}))
vi.mock('@/i18n/navigation', () => ({
  useRouter: () => routerMock,
}))
vi.mock('@/lib/api', () => ({
  authApi: authApiMock,
}))
vi.mock('@/lib/auth-storage', () => ({
  setAuthSession: sessionMock.setAuthSession,
}))
vi.mock('@/lib/oidc', () => ({
  startOidcLogin: vi.fn(),
}))
vi.mock('@/lib/oidc-providers', () => ({
  getOidcPublicProvidersFromEnv: () => [],
}))

import AuthPage from './page'

function setInputValue(input: HTMLInputElement | null, value: string) {
  expect(input).not.toBeNull()
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
    setter?.call(input, value)
    input?.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

function clickButtonByText(container: HTMLElement, text: string) {
  const button = Array.from(container.querySelectorAll('button')).find((candidate) =>
    candidate.textContent?.includes(text)
  )
  expect(button).not.toBeUndefined()
  act(() => button?.dispatchEvent(new MouseEvent('click', { bubbles: true })))
}

async function submitForm(container: HTMLElement) {
  await act(async () => {
    container
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await Promise.resolve()
  })
}

describe('auth page registration', () => {
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    authApiMock.login.mockReset()
    authApiMock.register.mockReset()
    routerMock.push.mockReset()
    sessionMock.setAuthSession.mockReset()
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.clearAllMocks()
  })

  it('passes the optional bootstrap token during first-owner registration', async () => {
    authApiMock.register.mockResolvedValue({
      token: { access_token: 'token', token_type: 'bearer', expires_in: 3600 },
      user: { id: 'owner-1' },
    })

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(<AuthPage />)
    })

    clickButtonByText(container, '首次设置')
    setInputValue(container.querySelector('#email'), 'owner@example.com')
    setInputValue(container.querySelector('#username'), 'owner')
    setInputValue(container.querySelector('#bootstrapToken'), 'bootstrap-secret')
    setInputValue(container.querySelector('#password'), 'correct-horse-battery-staple')
    setInputValue(container.querySelector('#confirmPassword'), 'correct-horse-battery-staple')

    await submitForm(container)

    await vi.waitFor(() =>
      expect(authApiMock.register).toHaveBeenCalledWith({
        email: 'owner@example.com',
        username: 'owner',
        password: 'correct-horse-battery-staple',
        bootstrapToken: 'bootstrap-secret',
      })
    )
    expect(sessionMock.setAuthSession).toHaveBeenCalledWith({
      token: { access_token: 'token', token_type: 'bearer', expires_in: 3600 },
      user: { id: 'owner-1' },
    })
    expect(routerMock.push).toHaveBeenCalledWith('/')

    act(() => root.unmount())
  })

  it('shows a clear bootstrap-token hint on 403 registration failures', async () => {
    authApiMock.register.mockRejectedValue({
      response: {
        status: 403,
        data: { detail: 'Initial registration bootstrap token required' },
      },
    })

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(<AuthPage />)
    })

    clickButtonByText(container, '首次设置')
    setInputValue(container.querySelector('#email'), 'owner@example.com')
    setInputValue(container.querySelector('#username'), 'owner')
    setInputValue(container.querySelector('#password'), 'correct-horse-battery-staple')
    setInputValue(container.querySelector('#confirmPassword'), 'correct-horse-battery-staple')

    await submitForm(container)

    await vi.waitFor(() => {
      expect(container.textContent).toContain('首次 owner 注册需要 bootstrap token。请填写部署时配置的 bootstrap token 后重试。')
    })

    act(() => root.unmount())
  })
})
