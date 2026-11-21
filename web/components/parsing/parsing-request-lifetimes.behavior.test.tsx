// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  parsing: { extract: vi.fn() },
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api/parsing', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/parsing')>()),
  parsingApi: api.parsing,
}))
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn() }))
import { ParsingExtractPanel } from './parsing-extract-panel'
import type { ParsingElement, ParsingExtractResponse } from '@/lib/api/parsing'
import { clearAuthSession, setAuthSession } from '@/lib/auth-storage'

const cleanups: Array<() => void> = []
const elements: ParsingElement[] = []

function session() {
  setAuthSession({
    user: {
      id: 'review-user',
      username: 'review-user',
      email: 'review@example.test',
      is_active: true,
      created_at: '2026-11-05T00:00:00Z',
      last_login_at: null,
    },
    token: { access_token: 'review-token', token_type: 'bearer', expires_in: 3600 },
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function extraction(documentId: string, value: string): ParsingExtractResponse {
  return {
    document_id: documentId,
    mode: 'schema',
    result: { field: { value, strategy: 'schema', evidence: [{ element_id: 'element-a', kind: 'seal', page: 1 }] } },
  }
}

function mount(initial: React.ReactElement) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const render = (element: React.ReactElement) => act(() => root.render(element))
  cleanups.push(() => {
    act(() => root.unmount())
    container.remove()
  })
  render(initial)
  return { container, render }
}

function click(view: ReturnType<typeof mount>, text: string) {
  const button = Array.from(view.container.querySelectorAll('button')).find((button) =>
    button.textContent?.trim().startsWith(text),
  )
  expect(button, text).toBeDefined()
  act(() => button!.click())
  return button!
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  localStorage.clear()
  sessionStorage.clear()
  clearAuthSession()
  session()
  vi.clearAllMocks()
  api.parsing.extract.mockReset()
})

afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
})

describe('extraction document ownership', () => {
  it('does not publish an older document result under the replacement document', async () => {
    const response = deferred<ParsingExtractResponse>()
    api.parsing.extract.mockReturnValue(response.promise)
    const view = mount(<ParsingExtractPanel documentId="first" activeElements={elements} onSelectEvidence={() => {}} />)
    click(view, '展开')
    click(view, '运行抽取')
    view.render(<ParsingExtractPanel documentId="second" activeElements={elements} onSelectEvidence={() => {}} />)
    click(view, '展开')

    await act(async () => response.resolve(extraction('first', 'retired extraction value')))

    expect(view.container.textContent).not.toContain('retired extraction value')
  })

  it('does not publish an older extraction failure under the replacement document', async () => {
    const response = deferred<ParsingExtractResponse>()
    api.parsing.extract.mockReturnValue(response.promise)
    const view = mount(<ParsingExtractPanel documentId="first" activeElements={elements} onSelectEvidence={() => {}} />)
    click(view, '展开')
    click(view, '运行抽取')
    view.render(<ParsingExtractPanel documentId="second" activeElements={elements} onSelectEvidence={() => {}} />)
    click(view, '展开')

    await act(async () => response.reject(new Error('retired extraction failure')))

    expect(view.container.textContent).not.toContain('retired extraction failure')
  })

  it('lets the replacement document run while an older request remains pending', async () => {
    const previous = deferred<ParsingExtractResponse>()
    const current = deferred<ParsingExtractResponse>()
    api.parsing.extract.mockReturnValueOnce(previous.promise).mockReturnValueOnce(current.promise)
    const view = mount(<ParsingExtractPanel documentId="first" activeElements={elements} onSelectEvidence={() => {}} />)
    click(view, '展开')
    click(view, '运行抽取')
    view.render(<ParsingExtractPanel documentId="second" activeElements={elements} onSelectEvidence={() => {}} />)
    click(view, '展开')
    const button = click(view, '运行抽取')

    expect(api.parsing.extract).toHaveBeenCalledTimes(2)
    await act(async () => previous.resolve(extraction('first', 'retired extraction')))
    expect(button.disabled).toBe(true)
    await act(async () => current.resolve(extraction('second', 'current extraction')))
    expect(button.disabled).toBe(false)
    expect(view.container.textContent).toContain('current extraction')
  })

  it('preserves the current payload and selectable evidence', async () => {
    const response = extraction('current', 'current value')
    api.parsing.extract.mockResolvedValue(response)
    const onSelectEvidence = vi.fn()
    const view = mount(
      <ParsingExtractPanel documentId="current" activeElements={elements} onSelectEvidence={onSelectEvidence} />,
    )
    click(view, '展开')
    click(view, '运行抽取')
    await act(async () => {})

    expect(api.parsing.extract).toHaveBeenCalledWith(
      'current',
      expect.objectContaining({ mode: 'schema', max_evidence: 3 }),
    )
    act(() => view.container.querySelector<HTMLButtonElement>('[data-testid="extract-evidence-button"]')!.click())
    expect(onSelectEvidence).toHaveBeenCalledWith({ fieldName: 'field', evidence: response.result.field.evidence[0] })
  })
})
