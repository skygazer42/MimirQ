// @vitest-environment happy-dom

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

function findButtonByText(container: HTMLElement, text: string) {
  const button = Array.from(container.querySelectorAll('button')).find((candidate) =>
    candidate.textContent?.includes(text)
  )
  expect(button).not.toBeUndefined()
  return button as HTMLButtonElement
}

function clickButtonByText(container: HTMLElement, text: string) {
  const button = findButtonByText(container, text)
  act(() => button.dispatchEvent(new MouseEvent('click', { bubbles: true })))
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
    delete process.env.NEXT_PUBLIC_ADMIN_CONTACT_URL
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.clearAllMocks()
    delete process.env.NEXT_PUBLIC_ADMIN_CONTACT_URL
  })

  it('renders contact administrator as a safe clickable link', () => {
    process.env.NEXT_PUBLIC_ADMIN_CONTACT_URL = 'mailto:ops@example.com'

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(<AuthPage />)
    })

    const contact = container.querySelector<HTMLAnchorElement>('a[href="mailto:ops@example.com"]')
    expect(contact?.textContent).toContain('联系管理员')

    act(() => root.unmount())
  })

  it('falls back to the project support page for an unsafe contact target', () => {
    process.env.NEXT_PUBLIC_ADMIN_CONTACT_URL = 'javascript:alert(1)'

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(<AuthPage />)
    })

    const contact = Array.from(container.querySelectorAll<HTMLAnchorElement>('a')).find((link) =>
      link.textContent?.includes('联系管理员')
    )
    expect(contact?.href).toBe('https://github.com/skygazer42/MimirQ/issues')

    act(() => root.unmount())
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

  it('explains how an apparently fresh deployment can already have an owner', async () => {
    authApiMock.register.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: 'Initial registration is closed; contact an administrator' },
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
      expect(container.textContent).toContain('已有初始化数据')
      expect(container.textContent).toContain('请使用已配置账号登录')
      expect(container.textContent).toContain('INITIAL_ADMIN_*')
      expect(container.textContent).toContain('持久化 Docker 数据卷')
      expect(container.textContent).toContain('bootstrap smoke')
    })

    act(() => root.unmount())
  })

  it('clears a login error when switching to first-time setup', async () => {
    authApiMock.login.mockRejectedValue({
      response: {
        status: 401,
        data: { detail: 'Invalid credentials' },
      },
    })

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(<AuthPage />)
    })

    setInputValue(container.querySelector('#identifier'), 'unknown-user')
    setInputValue(container.querySelector('#password'), 'wrong-password')
    await submitForm(container)

    await vi.waitFor(() => {
      expect(container.querySelector('[role="alert"]')?.textContent).toContain('Invalid credentials')
    })

    clickButtonByText(container, '首次设置')

    expect(container.querySelector('[role="alert"]')).toBeNull()
    expect(container.textContent).not.toContain('Invalid credentials')

    act(() => root.unmount())
  })

  it('keeps the auth frame vertically scrollable when setup content grows', () => {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(<AuthPage />)
    })

    const frame = container.firstElementChild
    expect(frame?.classList.contains('overflow-y-auto')).toBe(true)
    expect(frame?.classList.contains('overflow-hidden')).toBe(false)

    act(() => root.unmount())
  })

  it('announces the active auth mode through pressed button state', () => {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(<AuthPage />)
    })

    const loginButton = findButtonByText(container, '登录')
    const registerButton = findButtonByText(container, '首次设置')

    expect(loginButton.getAttribute('aria-pressed')).toBe('true')
    expect(registerButton.getAttribute('aria-pressed')).toBe('false')

    clickButtonByText(container, '首次设置')

    expect(loginButton.getAttribute('aria-pressed')).toBe('false')
    expect(registerButton.getAttribute('aria-pressed')).toBe('true')

    act(() => root.unmount())
  })
})
