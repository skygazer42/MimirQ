// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { NextIntlClientProvider } from 'next-intl'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import commandMessages from '@/i18n/messages/zh-CN/command'
import commonMessages from '@/i18n/messages/zh-CN/common'
import { globalEventBus } from '@/lib/event-bus'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  setOpen: vi.fn(),
  setTheme: vi.fn(),
  openDocument: vi.fn(),
  reopenLastDocument: vi.fn(),
  toggle: vi.fn(),
  documents: [] as Array<{ id: string; filename: string }>,
}))

vi.mock('@/i18n/navigation', () => ({
  usePathname: () => '/',
  useRouter: () => ({ push: mocks.push }),
}))
vi.mock('next-themes', () => ({ useTheme: () => ({ setTheme: mocks.setTheme }) }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: ({ queryKey }: { queryKey: readonly unknown[] }) => ({
    data: queryKey[0] === 'documents' ? mocks.documents : [],
    isFetching: false,
  }),
}))
vi.mock('@/hooks/use-tenant-access', () => ({ useTenantAccess: () => ({ data: undefined }) }))
vi.mock('@/lib/navigation-visibility', () => ({ canShowAdminControlledNavigationModule: () => true }))
vi.mock('@/lib/api', () => ({ documentApi: {}, datasetApi: {}, chatApi: {} }))
vi.mock('@/store/command-menu', () => ({
  useCommandMenuState: (select: (state: unknown) => unknown) => select({
    open: true, setOpen: mocks.setOpen, toggle: mocks.toggle,
  }),
}))
vi.mock('@/store/document-view', () => ({
  useDocumentView: () => ({
    lastOpenedTarget: null,
    openDocument: mocks.openDocument,
    reopenLastDocument: mocks.reopenLastDocument,
  }),
}))

import { CommandMenu } from './command-menu'

let root: Root

beforeEach(async () => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  Element.prototype.scrollIntoView = vi.fn()
  const container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="zh-CN" timeZone="Asia/Shanghai" messages={{ ...commonMessages, ...commandMessages }}>
        <CommandMenu />
      </NextIntlClientProvider>
    )
  })
})

afterEach(async () => {
  await act(async () => root.unmount())
  document.body.innerHTML = ''
  mocks.documents.length = 0
  vi.useRealTimers()
  vi.clearAllMocks()
})

async function query(value: string) {
  await act(async () => {
    globalEventBus.emit('command-menu:set-open', { open: true, query: value })
  })
}

async function expectExecution(label: string) {
  await act(async () => {
    await vi.waitFor(() => expect(executionButton()?.getAttribute('aria-label')).toBe(label))
  })
}

async function pressKey(element: Element, key: string) {
  await act(async () => {
    element.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
  })
}

function executionButton() {
  return document.querySelector<HTMLButtonElement>('[data-command-execute]')
}

describe('command menu explicit execution', () => {
  it('opens the selected command once through the visible action button', async () => {
    await query('/upload')
    await expectExecution('打开：上传文档')
    mocks.setOpen.mockClear()
    await act(async () => executionButton()?.click())
    expect(mocks.push).toHaveBeenCalledExactlyOnceWith('/knowledge')
    expect(mocks.setOpen).toHaveBeenCalledExactlyOnceWith(false)
  })

  it('offers a short question and sends that exact question to the conversation', async () => {
    await query('你好')
    await expectExecution('提问：向知识库提问')
    await act(async () => executionButton()?.click())
    expect(mocks.push).toHaveBeenCalledTimes(1)
    const target = new URL(mocks.push.mock.calls[0][0], 'http://localhost')
    expect(target.pathname).toBe('/')
    expect(target.searchParams.get('prompt')).toBe('你好')
    expect(target.searchParams.get('autorun')).toBe('1')
  })

  it('disables unavailable document restoration without closing or running an action', async () => {
    await query('/resume')
    const option = document.querySelector('[cmdk-item]')
    expect(option?.getAttribute('data-disabled')).toBe('true')
    expect(executionButton()).not.toBeNull()
    expect(executionButton()?.disabled).toBe(true)
    mocks.setOpen.mockClear()
    await act(async () => executionButton()?.click())
    expect(mocks.reopenLastDocument).not.toHaveBeenCalled()
    expect(mocks.push).not.toHaveBeenCalled()
    expect(mocks.setOpen).not.toHaveBeenCalled()
  })

  it('updates the footer with keyboard selection and executes the same action with Enter', async () => {
    await query('/')
    await expectExecution('打开：上传文档')
    const input = document.querySelector('[cmdk-input]')!
    await pressKey(input, 'ArrowDown')
    await expectExecution('提问：分析当前视图')
    await pressKey(input, 'Enter')
    expect(mocks.push).toHaveBeenCalledTimes(1)
    const target = new URL(mocks.push.mock.calls[0][0], 'http://localhost')
    expect(target.searchParams.get('autorun')).toBe('1')
    expect(target.searchParams.get('prompt')).toContain('当前所在页面')
  })

  it('does not let the footer Enter key bubble into a second command execution', async () => {
    await query('/upload')
    await expectExecution('打开：上传文档')
    const button = executionButton()!
    await pressKey(button, 'Enter')
    expect(mocks.push).not.toHaveBeenCalled()
    // Browser activation clicks a focused native button after keydown.
    await act(async () => button.click())
    expect(mocks.push).toHaveBeenCalledExactlyOnceWith('/knowledge')
  })

  it('keeps an unmatched slash query editable and prevents a stale action', async () => {
    await query('/upload')
    await expectExecution('打开：上传文档')
    await query('/no-such-command')
    expect(executionButton()?.disabled).toBe(true)
    expect(document.querySelector<HTMLInputElement>('[cmdk-input]')?.value).toBe('/no-such-command')
    await pressKey(document.querySelector('[cmdk-input]')!, 'Enter')
    expect(mocks.push).not.toHaveBeenCalled()
  })

  it('keeps text search working and distinguishes results that share a filename', async () => {
    vi.useFakeTimers()
    mocks.documents.push(
      { id: 'doc-1', filename: '设计说明.pdf' },
      { id: 'doc-2', filename: '设计说明.pdf' },
    )
    await query('设计')
    await act(async () => { await vi.advanceTimersByTimeAsync(220) })
    const input = document.querySelector('[cmdk-input]')!
    await pressKey(input, 'ArrowDown')
    await pressKey(input, 'ArrowDown')
    expect(executionButton()?.getAttribute('aria-label')).toBe('打开：设计说明.pdf')
    await act(async () => executionButton()?.click())
    expect(mocks.openDocument).toHaveBeenCalledExactlyOnceWith('doc-2')
    expect(mocks.push).toHaveBeenCalledExactlyOnceWith('/')
  })
})
