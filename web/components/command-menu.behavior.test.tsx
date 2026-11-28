// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { NextIntlClientProvider } from 'next-intl'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import commandMessages from '@/i18n/messages/zh-CN/command'
import commonMessages from '@/i18n/messages/zh-CN/common'

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
vi.mock('@/lib/api/documents', () => ({ documentApi: {} }))
vi.mock('@/lib/api/datasets', () => ({ datasetApi: {} }))
vi.mock('@/lib/api/chat', () => ({ chatApi: {} }))
vi.mock('@/store/command-menu', () => ({
  useCommandMenuState: (select: (state: unknown) => unknown) =>
    select({
      open: true,
      setOpen: mocks.setOpen,
      toggle: mocks.toggle,
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
      <NextIntlClientProvider
        locale="zh-CN"
        timeZone="Asia/Shanghai"
        messages={{ ...commonMessages, ...commandMessages }}
      >
        <CommandMenu />
      </NextIntlClientProvider>,
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
  const input = document.querySelector<HTMLInputElement>('[cmdk-input]')!
  const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => {
    setValue.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

async function expectSelectedCommand(value: string) {
  await act(async () => {
    await vi.waitFor(() => expect(command(value)?.getAttribute('aria-selected')).toBe('true'))
  })
}

async function pressKey(element: Element, key: string) {
  await act(async () => {
    element.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
  })
}

function command(value: string) {
  return document.querySelector<HTMLElement>(`[cmdk-item][data-value="${value}"]`)
}

describe('command menu explicit execution', () => {
  it('opens the independent ontology studio from its searchable module command', async () => {
    await query('ontology')
    expect(command('module:ontology')?.textContent).toContain('企业本体')
    await act(async () => command('module:ontology')?.click())
    expect(mocks.push).toHaveBeenCalledExactlyOnceWith('/ontology')
    expect(mocks.setOpen).toHaveBeenCalledExactlyOnceWith(false)
  })

  it('opens the selected command once through its result row', async () => {
    await query('/upload')
    await expectSelectedCommand('slash:upload')
    mocks.setOpen.mockClear()
    await act(async () => command('slash:upload')?.click())
    expect(mocks.push).toHaveBeenCalledExactlyOnceWith('/knowledge')
    expect(mocks.setOpen).toHaveBeenCalledExactlyOnceWith(false)
  })

  it('offers a short question and sends that exact question to the conversation', async () => {
    await query('你好')
    await expectSelectedCommand('ai 你好')
    await act(async () => command('ai 你好')?.click())
    expect(mocks.push).toHaveBeenCalledTimes(1)
    const target = new URL(mocks.push.mock.calls[0][0], 'http://localhost')
    expect(target.pathname).toBe('/')
    expect(target.searchParams.get('prompt')).toBe('你好')
    expect(target.searchParams.get('autorun')).toBe('1')
  })

  it('disables unavailable document restoration without closing or running an action', async () => {
    await query('/resume')
    const option = command('slash:resume')
    expect(option?.getAttribute('data-disabled')).toBe('true')
    mocks.setOpen.mockClear()
    await act(async () => option?.click())
    await pressKey(document.querySelector('[cmdk-input]')!, 'Enter')
    expect(mocks.reopenLastDocument).not.toHaveBeenCalled()
    expect(mocks.push).not.toHaveBeenCalled()
    expect(mocks.setOpen).not.toHaveBeenCalled()
  })

  it('moves keyboard selection and executes the selected result with Enter', async () => {
    await query('/')
    await expectSelectedCommand('slash:upload')
    const input = document.querySelector('[cmdk-input]')!
    await pressKey(input, 'ArrowDown')
    await expectSelectedCommand('slash:analyze')
    await pressKey(input, 'Enter')
    expect(mocks.push).toHaveBeenCalledTimes(1)
    const target = new URL(mocks.push.mock.calls[0][0], 'http://localhost')
    expect(target.searchParams.get('autorun')).toBe('1')
    expect(target.searchParams.get('prompt')).toContain('当前所在页面')
  })

  it('closes the command menu without executing the highlighted command', async () => {
    await query('/upload')
    await expectSelectedCommand('slash:upload')
    const button = document.querySelector<HTMLButtonElement>('button[aria-label="关闭命令中心"]')!
    mocks.setOpen.mockClear()
    await pressKey(button, 'Enter')
    expect(mocks.push).not.toHaveBeenCalled()
    // Browser activation clicks a focused native button after keydown.
    await act(async () => button.click())
    expect(mocks.push).not.toHaveBeenCalled()
    expect(mocks.setOpen).toHaveBeenCalledExactlyOnceWith(false)
  })

  it('keeps an unmatched slash query editable and prevents a stale action', async () => {
    await query('/upload')
    await expectSelectedCommand('slash:upload')
    await query('/no-such-command')
    expect(document.querySelector('[cmdk-item][aria-disabled="false"]')).toBeNull()
    expect(document.querySelector<HTMLInputElement>('[cmdk-input]')?.value).toBe('/no-such-command')
    await pressKey(document.querySelector('[cmdk-input]')!, 'Enter')
    expect(mocks.push).not.toHaveBeenCalled()
  })

  it('opens dataset selection for precheck scans and reports', async () => {
    await query('/precheck')
    await expectSelectedCommand('slash:precheck')
    await act(async () => command('slash:precheck')?.click())
    expect(mocks.push).toHaveBeenLastCalledWith('/datasets')

    await query('/report')
    await expectSelectedCommand('slash:report')
    await act(async () => command('slash:report')?.click())
    expect(mocks.push).toHaveBeenLastCalledWith('/datasets')
  })

  it.each(['/retry-failed', '/pause-active'])('does not offer an unsupported bulk action for %s', async (command) => {
    await query(command)
    expect(document.querySelector('[cmdk-item]')).toBeNull()
    await pressKey(document.querySelector('[cmdk-input]')!, 'Enter')
    expect(mocks.push).not.toHaveBeenCalled()
  })

  it('keeps text search working and distinguishes results that share a filename', async () => {
    vi.useFakeTimers()
    mocks.documents.push({ id: 'doc-1', filename: '设计说明.pdf' }, { id: 'doc-2', filename: '设计说明.pdf' })
    await query('设计')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(220)
    })
    const input = document.querySelector('[cmdk-input]')!
    await pressKey(input, 'ArrowDown')
    await pressKey(input, 'ArrowDown')
    expect(command('document:doc-2')?.getAttribute('aria-selected')).toBe('true')
    await act(async () => command('document:doc-2')?.click())
    expect(mocks.openDocument).toHaveBeenCalledExactlyOnceWith('doc-2')
    expect(mocks.push).toHaveBeenCalledExactlyOnceWith('/')
  })
})
