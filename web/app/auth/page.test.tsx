// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() } }))

const authApiMock = vi.hoisted(() => ({
  login: vi.fn(),
  register: vi.fn(),
  signup: vi.fn(),
  policy: vi.fn(),
}))
const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
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
vi.mock('@/lib/api/auth', () => ({
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
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
    authApiMock.login.mockReset()
    authApiMock.register.mockReset()
    authApiMock.signup.mockReset()
    authApiMock.policy.mockReset().mockResolvedValue({
      initialized: true, registration_enabled: true, bootstrap_enabled: false,
      bootstrap_token_required: false, password_min_length: 8,
    })
    routerMock.push.mockReset()
    routerMock.replace.mockReset()
    sessionMock.setAuthSession.mockReset()
    window.history.replaceState(null, '', '/auth')
    delete process.env.NEXT_PUBLIC_ADMIN_CONTACT_URL
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.clearAllMocks()
    window.history.replaceState(null, '', '/auth')
    delete process.env.NEXT_PUBLIC_ADMIN_CONTACT_URL
  })

  it('renders contact administrator as a safe clickable link', async () => {
    process.env.NEXT_PUBLIC_ADMIN_CONTACT_URL = 'mailto:ops@example.com'
    authApiMock.policy.mockResolvedValue({
      initialized: true, registration_enabled: false, bootstrap_enabled: false,
      bootstrap_token_required: false, password_min_length: 8,
    })

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => {
      root.render(<AuthPage />)
    })

    const contact = container.querySelector<HTMLAnchorElement>('a[href="mailto:ops@example.com"]')
    expect(contact?.textContent).toContain('联系管理员')

    act(() => root.unmount())
  })

  it('falls back to the project support page for an unsafe contact target', async () => {
    process.env.NEXT_PUBLIC_ADMIN_CONTACT_URL = 'javascript:alert(1)'
    authApiMock.policy.mockResolvedValue({
      initialized: true, registration_enabled: false, bootstrap_enabled: false,
      bootstrap_token_required: false, password_min_length: 8,
    })

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => {
      root.render(<AuthPage />)
    })

    const contact = Array.from(container.querySelectorAll<HTMLAnchorElement>('a')).find((link) =>
      link.textContent?.includes('联系管理员')
    )
    expect(contact?.href).toBe('https://github.com/skygazer42/MimirQ/issues')

    act(() => root.unmount())
  })







  it('clears a login error when switching to ordinary registration', async () => {
    authApiMock.login.mockRejectedValue({
      response: {
        status: 401,
        data: { detail: 'Invalid credentials' },
      },
    })

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => {
      root.render(<AuthPage />)
    })

    setInputValue(container.querySelector('#identifier'), 'unknown-user')
    setInputValue(container.querySelector('#password'), 'wrong-password')
    await submitForm(container)

    await vi.waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('账号或密码不正确，请重试。', expect.objectContaining({ duration: 4000 }))
    })

    clickButtonByText(container, '注册')

    expect(container.querySelector('[role="alert"]')).toBeNull()
    expect(container.textContent).not.toContain('账号或密码不正确，请重试。')

    act(() => root.unmount())
  })

  it('keeps the auth frame vertically scrollable when registration content grows', async () => {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => {
      root.render(<AuthPage />)
    })

    const frame = container.firstElementChild
    const main = container.querySelector('#main-content')
    expect(frame?.classList.contains('overflow-y-auto')).toBe(true)
    expect(frame?.classList.contains('overflow-hidden')).toBe(false)
    expect(main).not.toBeNull()
    expect(main?.classList.contains('overflow-hidden')).toBe(false)

    act(() => root.unmount())
  })

  it('offers the opposite auth action and updates the heading when switching modes', async () => {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => {
      root.render(<AuthPage />)
    })

    expect(container.querySelector('h1')?.textContent).toBe('欢迎回来')
    expect(container.querySelector('[data-auth-mode-switch] button')?.textContent).toBe('注册')

    clickButtonByText(container, '注册')

    expect(container.querySelector('h1')?.textContent).toBe('创建账号')
    expect(container.querySelector('[data-auth-mode-switch] button')?.textContent).toBe('登录')

    act(() => root.unmount())
  })

  it('registers through signup and returns to login without creating a session', async () => {
    authApiMock.policy.mockResolvedValue({
      initialized: true, registration_enabled: true, bootstrap_enabled: false,
      bootstrap_token_required: false, password_min_length: 12,
    })
    const session = {
      token: { access_token: 'reader-token', token_type: 'bearer', expires_in: 3600 },
      user: { id: 'reader-1', username: 'reader', email: 'reader@example.com' },
    }
    authApiMock.signup.mockResolvedValue(session)
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    await act(async () => { root.render(<AuthPage />) })

    expect(container.textContent).not.toContain('首次设置')
    clickButtonByText(container, '注册')
    expect(container.querySelector('#bootstrapToken')).toBeNull()
    expect(container.querySelector('#password')?.getAttribute('minlength')).toBe('12')
    setInputValue(container.querySelector('#email'), ' reader@example.com ')
    setInputValue(container.querySelector('#username'), ' reader ')
    setInputValue(container.querySelector('#password'), 'valid-reader-password')
    setInputValue(container.querySelector('#confirmPassword'), 'valid-reader-password')
    await submitForm(container)

    expect(authApiMock.signup).toHaveBeenCalledWith({
      email: 'reader@example.com', username: 'reader', password: 'valid-reader-password',
    })
    expect(authApiMock.register).not.toHaveBeenCalled()
    expect(sessionMock.setAuthSession).not.toHaveBeenCalled()
    expect(routerMock.push).not.toHaveBeenCalled()
    expect(routerMock.replace).toHaveBeenCalledWith('/auth')
    expect(container.querySelector('h1')?.textContent).toBe('欢迎回来')
    expect(container.querySelector<HTMLInputElement>('#identifier')?.value).toBe('reader@example.com')
    expect(container.querySelector<HTMLInputElement>('#password')?.value).toBe('')
    expect(container.querySelector('#confirmPassword')).toBeNull()
    expect(toast.success).toHaveBeenCalledWith('注册成功，请登录。', expect.objectContaining({ duration: 4000 }))
    act(() => root.unmount())
  })

  it('returns a direct registration link to login and only creates a session after login', async () => {
    window.history.replaceState(null, '', '/auth?mode=register')
    const session = {
      token: { access_token: 'reader-token', token_type: 'bearer', expires_in: 3600 },
      user: { id: 'reader-1', username: 'reader', email: 'reader@example.com' },
    }
    authApiMock.signup.mockResolvedValue(session)
    const container = document.createElement('div')
    const root = createRoot(container)
    await act(async () => { root.render(<AuthPage />) })

    expect(container.querySelector('h1')?.textContent).toBe('创建账号')
    setInputValue(container.querySelector('#email'), 'reader@example.com')
    setInputValue(container.querySelector('#username'), 'reader')
    setInputValue(container.querySelector('#password'), 'valid-reader-password')
    setInputValue(container.querySelector('#confirmPassword'), 'valid-reader-password')
    await submitForm(container)

    expect(authApiMock.signup).toHaveBeenCalledWith({
      email: 'reader@example.com', username: 'reader', password: 'valid-reader-password',
    })
    expect(sessionMock.setAuthSession).not.toHaveBeenCalled()
    expect(routerMock.push).not.toHaveBeenCalled()
    expect(routerMock.replace).toHaveBeenCalledWith('/auth')
    expect(container.querySelector('h1')?.textContent).toBe('欢迎回来')
    expect(container.querySelector<HTMLInputElement>('#identifier')?.value).toBe('reader@example.com')
    expect(container.querySelector<HTMLInputElement>('#password')?.value).toBe('')

    authApiMock.login.mockResolvedValue(session)
    setInputValue(container.querySelector('#password'), 'valid-reader-password')
    await submitForm(container)
    expect(authApiMock.login).toHaveBeenCalledWith({
      identifier: 'reader@example.com', password: 'valid-reader-password',
    })
    expect(sessionMock.setAuthSession).toHaveBeenCalledWith(session)
    expect(routerMock.push).toHaveBeenCalledWith('/')
    expect(container.querySelector('[role="status"]')).toBeNull()
    act(() => root.unmount())
  })

  it('stays on registration without a success notice when signup fails', async () => {
    authApiMock.signup.mockRejectedValue(new Error('注册失败'))
    const container = document.createElement('div')
    const root = createRoot(container)
    await act(async () => { root.render(<AuthPage />) })
    clickButtonByText(container, '注册')
    setInputValue(container.querySelector('#email'), 'reader@example.com')
    setInputValue(container.querySelector('#username'), 'reader')
    setInputValue(container.querySelector('#password'), 'valid-reader-password')
    setInputValue(container.querySelector('#confirmPassword'), 'valid-reader-password')
    await submitForm(container)
    expect(container.querySelector('h1')?.textContent).toBe('创建账号')
    expect(toast.error).toHaveBeenCalled()
    expect(container.textContent).not.toContain('注册成功')
    expect(routerMock.replace).not.toHaveBeenCalled()
    expect(sessionMock.setAuthSession).not.toHaveBeenCalled()
    act(() => root.unmount())
  })

  it('keeps a registration link on login when the server closes registration', async () => {
    window.history.replaceState(null, '', '/auth?mode=register')
    authApiMock.policy.mockResolvedValue({
      initialized: true, registration_enabled: false, bootstrap_enabled: false,
      bootstrap_token_required: false, password_min_length: 8,
    })
    const container = document.createElement('div')
    const root = createRoot(container)
    await act(async () => { root.render(<AuthPage />) })
    expect(container.querySelector('h1')?.textContent).toBe('欢迎回来')
    expect(container.querySelector('#email')).toBeNull()
    expect(authApiMock.signup).not.toHaveBeenCalled()
    act(() => root.unmount())
  })

  it('offers only login when registration is closed on an initialized deployment', async () => {
    authApiMock.policy.mockResolvedValue({
      initialized: true, registration_enabled: false, bootstrap_enabled: false,
      bootstrap_token_required: false, password_min_length: 8,
    })
    const container = document.createElement('div')
    const root = createRoot(container)
    await act(async () => { root.render(<AuthPage />) })
    expect(container.querySelector('[data-auth-mode-switch]')).toBeNull()
    expect(container.querySelector('#identifier')).not.toBeNull()
    expect(container.querySelector('#email')).toBeNull()
    expect(container.querySelector('button[type="submit"]')?.hasAttribute('disabled')).toBe(false)
    act(() => root.unmount())
  })

  it('does not expose legacy owner setup even if an older backend advertises it', async () => {
    authApiMock.policy.mockResolvedValue({
      initialized: false, registration_enabled: false, bootstrap_enabled: true,
      bootstrap_token_required: true, password_min_length: 8,
    })
    const container = document.createElement('div')
    const root = createRoot(container)
    await act(async () => { root.render(<AuthPage />) })
    expect(container.textContent).not.toContain('首次设置')
    expect(container.textContent).not.toContain('创建初始管理员')
    expect(container.querySelector('#bootstrapToken')).toBeNull()
    expect(container.querySelector('[data-auth-mode-switch]')).toBeNull()
    expect(authApiMock.register).not.toHaveBeenCalled()
    act(() => root.unmount())
  })

  it('keeps login usable and registration closed while policy is loading', async () => {
    let resolvePolicy!: (value: unknown) => void
    authApiMock.policy.mockReturnValue(new Promise((resolve) => { resolvePolicy = resolve }))
    const container = document.createElement('div')
    const root = createRoot(container)
    await act(async () => { root.render(<AuthPage />) })
    expect(container.querySelector('[data-auth-mode-switch]')).toBeNull()
    expect(container.querySelector('button[type="submit"]')?.hasAttribute('disabled')).toBe(false)
    await act(async () => { resolvePolicy({
      initialized: true, registration_enabled: true, bootstrap_enabled: false,
      bootstrap_token_required: false, password_min_length: 8,
    }) })
    expect(container.querySelector('[data-auth-mode-switch]')).not.toBeNull()
    act(() => root.unmount())
  })

  it('lets the user retry a failed policy request while retaining account login', async () => {
    authApiMock.policy.mockRejectedValueOnce(new Error('Network error')).mockResolvedValue({
      initialized: true, registration_enabled: true, bootstrap_enabled: false,
      bootstrap_token_required: false, password_min_length: 8,
    })
    const container = document.createElement('div')
    const root = createRoot(container)
    await act(async () => { root.render(<AuthPage />) })
    expect(container.querySelector('[data-auth-mode-switch]')).toBeNull()
    expect(container.querySelector('button[type="submit"]')?.hasAttribute('disabled')).toBe(false)
    setInputValue(container.querySelector('#identifier'), 'reader@example.com')
    setInputValue(container.querySelector('#password'), 'retained-password')
    await act(async () => { clickButtonByText(container, '重试') })
    expect(container.querySelector('[data-auth-mode-switch]')).not.toBeNull()
    expect(container.textContent).not.toContain('服务暂时不可用')
    expect(container.querySelector<HTMLInputElement>('#identifier')?.value).toBe('reader@example.com')
    expect(container.querySelector<HTMLInputElement>('#password')?.value).toBe('retained-password')
    act(() => root.unmount())
  })

  it('shows one readable service failure and keeps request details collapsed without discarding credentials', async () => {
    authApiMock.policy.mockRejectedValue({
      response: { status: 503, data: { detail: 'Service Unavailable' } },
    })
    authApiMock.login.mockRejectedValue({
      response: {
        status: 500,
        data: { detail: 'Internal Server Error', request_id: 'login-request-123' },
      },
    })
    const container = document.createElement('div')
    const root = createRoot(container)
    await act(async () => { root.render(<AuthPage />) })
    setInputValue(container.querySelector('#identifier'), 'reader@example.com')
    setInputValue(container.querySelector('#password'), 'retained-password')
    await submitForm(container)

    expect(toast.error).toHaveBeenCalledWith('服务暂时不可用，请稍后重试。', expect.objectContaining({ duration: 4000 }))
    expect(container.querySelectorAll('[role="alert"], [role="status"]')).toHaveLength(0)
    expect(container.textContent).not.toContain('Internal Server Error')
    expect(container.textContent).not.toContain('暂时无法获取注册方式')
    const details = container.querySelector('details')
    expect(details).not.toBeNull()
    expect(details?.open).toBe(false)
    expect(details?.querySelector('summary')?.textContent).toBe('错误详情')
    expect(details?.textContent).toContain('login-request-123')
    expect(container.querySelector<HTMLInputElement>('#identifier')?.value).toBe('reader@example.com')
    expect(container.querySelector<HTMLInputElement>('#password')?.value).toBe('retained-password')
    expect(sessionMock.setAuthSession).not.toHaveBeenCalled()
    expect(routerMock.push).not.toHaveBeenCalled()
    act(() => root.unmount())
  })



  it('explains closed ordinary registration without asking users for a bootstrap token', async () => {
    authApiMock.policy.mockResolvedValue({
      initialized: true, registration_enabled: true, bootstrap_enabled: false,
      bootstrap_token_required: false, password_min_length: 8,
    })
    authApiMock.signup.mockRejectedValue({ response: {
      status: 403, data: { detail: 'Account registration is disabled; contact an administrator' },
    } })
    const container = document.createElement('div')
    const root = createRoot(container)
    await act(async () => { root.render(<AuthPage />) })
    clickButtonByText(container, '注册')
    setInputValue(container.querySelector('#email'), 'reader@example.com')
    setInputValue(container.querySelector('#username'), 'reader')
    setInputValue(container.querySelector('#password'), 'valid-reader-password')
    setInputValue(container.querySelector('#confirmPassword'), 'valid-reader-password')
    await submitForm(container)
    expect(toast.error).toHaveBeenCalledWith('当前暂未开放注册，请联系管理员。', expect.objectContaining({ duration: 4000 }))
    expect(container.querySelector('#auth-error')?.textContent).not.toContain('令牌')
    expect(container.querySelector('#bootstrapToken')).toBeNull()
    act(() => root.unmount())
  })
})
