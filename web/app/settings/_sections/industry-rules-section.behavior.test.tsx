// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { queryKeys } from '@/lib/query-keys'
import { waitForAssertion } from '@/test/hook-harness'

const api = vi.hoisted(() => ({
  listRulesets: vi.fn(),
  getRuleset: vi.fn(),
  updateGlossary: vi.fn(),
  updatePatterns: vi.fn(),
  updateIntents: vi.fn(),
  previewRewrite: vi.fn(),
}))
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api/industry-rules', () => ({ industryRulesApi: api }))
vi.mock('sonner', () => ({ toast: notices }))
vi.mock('@/i18n/navigation', () => ({
  Link: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}))

import { setAuthSession } from '@/lib/auth-storage'
import { IndustryRulesSection } from './industry-rules-section'

const cleanup: Array<() => void> = []
const token = { access_token: 'rules-session', token_type: 'bearer', expires_in: 3600 }
const profile = {
  id: 'rules-user',
  username: 'rules-user',
  email: 'rules@example.com',
  is_active: true,
  created_at: '2026-11-05T00:00:00Z',
}

function detail(name = 'industrial_control') {
  return {
    schema: 'mimirq.industry_rules_ruleset.v1',
    ruleset: {
      name,
      glossary_count: 1,
      pattern_count: 1,
      intent_count: 1,
      glossary: { alarm: ['fault'] },
      patterns: [{ id: 'pattern', enabled: false, weight: 0, optional: null }],
      intents: [{ id: 'intent', enabled: false, threshold: 0, optional: null }],
    },
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept
    reject = fail
  })
  return { promise, resolve, reject }
}

async function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 10_000, gcTime: Infinity, refetchOnWindowFocus: false } },
  })
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const render = async () => {
    await act(async () =>
      root.render(
        <QueryClientProvider client={client}>
          <IndustryRulesSection />
        </QueryClientProvider>,
      ),
    )
  }
  let mounted = true
  const unmount = () => {
    if (!mounted) return
    mounted = false
    act(() => root.unmount())
    client.clear()
    container.remove()
  }
  cleanup.push(unmount)
  await render()
  return { container, client, render, unmount }
}

function button(container: ParentNode, label: string) {
  const match = [...container.querySelectorAll<HTMLButtonElement>('button')].find(
    (node) => node.textContent?.trim() === label,
  )
  expect(match, label).toBeDefined()
  return match!
}

function fill(input: HTMLInputElement | HTMLTextAreaElement, value: string) {
  act(() => {
    const prototype = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  setAuthSession({ token, user: profile })
  api.listRulesets.mockResolvedValue({
    schema: 'mimirq.industry_rules_index.v1',
    count: 1,
    rulesets: [{ name: 'industrial_control', glossary_count: 1, pattern_count: 1, intent_count: 1 }],
  })
  api.getRuleset.mockResolvedValue(detail())
  for (const method of [api.updateGlossary, api.updatePatterns, api.updateIntents])
    method.mockResolvedValue({
      schema: 'mimirq.industry_rules_update.v1',
      ruleset: 'industrial_control',
      section: 'test',
      updated_count: 1,
    })
})
afterEach(() => {
  for (const dispose of cleanup.splice(0).reverse()) dispose()
  document.body.innerHTML = ''
})

vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))
beforeEach(() => {
  let current = detail()
  api.getRuleset.mockImplementation(async () => structuredClone(current))
  for (const [key, method] of [
    ['glossary', api.updateGlossary],
    ['patterns', api.updatePatterns],
    ['intents', api.updateIntents],
  ] as const) {
    method.mockImplementation(async (_name, payload) => {
      current = { ...current, ruleset: { ...current.ruleset, ...payload } }
      return {
        schema: 'mimirq.industry_rules_update.v1',
        ruleset: current.ruleset.name,
        section: key,
        updated_count: 1,
      }
    })
  }
})
async function ready() {
  const view = await mount()
  await waitForAssertion(() => expect(view.container.querySelector('#industry-add-glossary')).not.toBeNull())
  return view
}
function jsonEditor(view: Awaited<ReturnType<typeof ready>>, section = 'glossary') {
  const labels = { glossary: '术语词库', patterns: '匹配规则', intents: '意图规则' }
  const tab = [...view.container.querySelectorAll<HTMLElement>('[role="tab"]')].find((node) =>
    node.textContent?.startsWith(labels[section as keyof typeof labels]),
  )!
  act(() => {
    tab.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }))
    tab.focus()
  })
  act(() => button(view.container, 'JSON 编辑').click())
  return view.container.querySelector<HTMLTextAreaElement>(`#industry-${section}-json`)!
}
const key = queryKeys.industryRules.ruleset('industrial_control')

describe('industry forms retain query, draft and session ownership', () => {
  it('keeps a late automatic read associated with its original ruleset', async () => {
    const pending = deferred<ReturnType<typeof detail>>()
    const current = {
      ...detail('other'),
      ruleset: { ...detail('other').ruleset, glossary: { alarm: ['current ruleset'] } },
    }
    api.getRuleset.mockReturnValueOnce(pending.promise).mockResolvedValue(current)
    const view = await mount()
    await waitForAssertion(() => expect(api.getRuleset).toHaveBeenCalledOnce())
    act(() =>
      view.client.setQueryData(queryKeys.industryRules.rulesets, {
        schema: 'mimirq.industry_rules_index.v1',
        count: 1,
        rulesets: [{ name: 'other', glossary_count: 1, pattern_count: 1, intent_count: 1 }],
      }),
    )
    await waitForAssertion(() => expect(view.container.querySelector('#industry-add-glossary')).not.toBeNull())
    const editor = jsonEditor(view)
    expect(editor.value).toContain('current ruleset')
    await act(async () => pending.resolve(detail()))
    expect(editor.value).toContain('current ruleset')
  })
  it.each(['session', 'query replacement', 'unmount'] as const)(
    'retires an in-flight preview on %s',
    async (reason) => {
      const view = await ready()
      const pending = deferred<unknown>()
      api.previewRewrite.mockReturnValueOnce(pending.promise)
      act(() => button(view.container, '测试展开').click())
      expect(api.previewRewrite).toHaveBeenCalledOnce()
      if (reason === 'session') act(() => setAuthSession({ token, user: profile }))
      else if (reason === 'query replacement')
        act(() => {
          view.client.removeQueries({ queryKey: key, exact: true })
          view.client.setQueryData(key, detail())
        })
      else view.unmount()
      await act(async () =>
        pending.resolve({
          ruleset: 'industrial_control',
          original_query: 'old preview',
          expanded_query: 'retired expanded value',
          changed: true,
        }),
      )
      expect(view.container.textContent).not.toContain('retired expanded value')
      expect(notices.error).not.toHaveBeenCalled()
    },
  )
  it('automatically loads rules once and retains an edited draft through a background read', async () => {
    const view = await ready()
    const editor = jsonEditor(view)
    fill(editor, '{"local":["draft"]}')
    const pending = deferred<ReturnType<typeof detail>>()
    api.getRuleset.mockReturnValueOnce(pending.promise)
    act(() => {
      void view.client.invalidateQueries({ queryKey: key, exact: true })
    })
    await waitForAssertion(() => expect(api.getRuleset).toHaveBeenCalledTimes(2))
    fill(editor, '{"newer":["draft"]}')
    await act(async () => pending.resolve(detail()))
    expect(editor.value).toBe('{"newer":["draft"]}')
    expect(notices.success).not.toHaveBeenCalled()
  })
  it('does not fabricate empty rules after an in-flight query is removed', async () => {
    const pending = deferred<ReturnType<typeof detail>>()
    api.getRuleset.mockReturnValueOnce(pending.promise)
    const view = await mount()
    await waitForAssertion(() => expect(api.getRuleset).toHaveBeenCalledOnce())
    act(() => view.client.removeQueries({ queryKey: key, exact: true }))
    await act(async () => pending.resolve(detail()))
    expect(view.container.querySelector('#industry-add-glossary')).toBeNull()
    expect(notices.success).not.toHaveBeenCalled()
  })
  it.each(['resolve', 'reject'] as const)('does not publish an automatic read %s after unmount', async (outcome) => {
    const pending = deferred<ReturnType<typeof detail>>()
    api.getRuleset.mockReturnValueOnce(pending.promise)
    const view = await mount()
    await waitForAssertion(() => expect(api.getRuleset).toHaveBeenCalledOnce())
    view.unmount()
    await act(async () =>
      outcome === 'resolve' ? pending.resolve(detail()) : pending.reject(new Error('retired load')),
    )
    expect(notices.success).not.toHaveBeenCalled()
    expect(notices.error).not.toHaveBeenCalled()
  })
  it('keeps the current load error recoverable through the real retry control', async () => {
    api.getRuleset.mockRejectedValue(new Error('current load failed'))
    const view = await mount()
    await waitForAssertion(() => expect(view.container.textContent).toContain('规则加载失败'), 2500)
    api.getRuleset.mockResolvedValue(detail())
    await act(async () => button(view.container, '重试加载').click())
    await waitForAssertion(() => expect(view.container.querySelector('#industry-add-glossary')).not.toBeNull())
  })
  it.each(['preview', 'patterns'] as const)('starts a fresh %s after idle cache removal', async (action) => {
    const view = await ready()
    let editor: HTMLTextAreaElement | null = null
    if (action === 'patterns') {
      editor = jsonEditor(view, 'patterns')
      fill(editor, '[{"markers":["new"],"enabled":false,"weight":0,"optional":null}]')
    }
    const previous = view.client.getQueryCache().find({ queryKey: key, exact: true })
    act(() => view.client.clear())
    if (action === 'preview') {
      api.previewRewrite.mockResolvedValue({
        ruleset: 'industrial_control',
        original_query: 'input',
        expanded_query: 'input',
        changed: false,
      })
      await act(async () => button(view.container, '测试展开').click())
      expect(api.previewRewrite).toHaveBeenCalledOnce()
    } else {
      await act(async () => button(view.container, '保存规则').click())
      expect(api.updatePatterns).toHaveBeenCalledOnce()
    }
    expect(view.client.getQueryCache().find({ queryKey: key, exact: true })).not.toBe(previous)
  })
  it('retires save completion after a silent explicit login with the same identity', async () => {
    const view = await ready()
    const editor = jsonEditor(view, 'patterns')
    fill(editor, '[{"markers":["new"],"enabled":false}]')
    const pending = deferred<unknown>()
    api.updatePatterns.mockReturnValueOnce(pending.promise)
    act(() => button(view.container, '保存规则').click())
    expect(api.updatePatterns).toHaveBeenCalledOnce()
    act(() => setAuthSession({ token, user: profile }))
    const invalidate = vi.spyOn(view.client, 'invalidateQueries')
    const reads = api.getRuleset.mock.calls.length
    await act(async () => pending.resolve({ updated_count: 1 }))
    expect(api.getRuleset).toHaveBeenCalledTimes(reads)
    expect(invalidate).not.toHaveBeenCalled()
    expect(notices.error).not.toHaveBeenCalled()
    expect(editor.value).toContain('"new"')
    expect(view.container.querySelector('[role="tab"]')).not.toBeNull()
  })
  it('does not publish a save into a removed and rebuilt query entity', async () => {
    const view = await ready()
    fill(jsonEditor(view, 'patterns'), '[{"markers":["new"]}]')
    const pending = deferred<unknown>()
    api.updatePatterns.mockReturnValueOnce(pending.promise)
    act(() => button(view.container, '保存规则').click())
    const replacement = detail()
    replacement.ruleset.glossary = { alarm: ['current replacement'] }
    act(() => {
      view.client.removeQueries({ queryKey: key, exact: true })
      view.client.setQueryData(key, replacement)
    })
    await act(async () => pending.resolve({ updated_count: 1 }))
    expect(view.client.getQueryData(key)).toBe(replacement)
    expect(notices.error).not.toHaveBeenCalled()
  })
})

describe('industry section payloads and failures', () => {
  it.each(['glossary', 'patterns', 'intents'] as const)(
    'writes and reads back only %s while retaining extension values',
    async (section) => {
      const view = await ready()
      const value =
        section === 'glossary' ? { alarm: ['new'] } : [{ markers: ['new'], enabled: false, weight: 0, optional: null }]
      fill(jsonEditor(view, section), JSON.stringify(value))
      const labels = { glossary: '保存词库', patterns: '保存规则', intents: '保存意图' }
      await act(async () => button(view.container, labels[section]).click())
      const methods = { glossary: api.updateGlossary, patterns: api.updatePatterns, intents: api.updateIntents }
      expect(methods[section]).toHaveBeenCalledExactlyOnceWith('industrial_control', { [section]: value })
      for (const other of ['glossary', 'patterns', 'intents'] as const)
        if (other !== section) expect(methods[other]).not.toHaveBeenCalled()
      expect(JSON.parse(view.container.querySelector<HTMLTextAreaElement>(`#industry-${section}-json`)!.value)).toEqual(
        value,
      )
    },
  )
  it.each(['{broken', 'null', ''] as const)(
    'keeps invalid JSON %s visible without defaulting or sending it',
    async (raw) => {
      const view = await ready()
      const editor = jsonEditor(view, 'patterns')
      fill(editor, raw)
      await act(async () => button(view.container, '保存规则').click())
      expect(editor.value).toBe(raw)
      expect(api.updatePatterns).not.toHaveBeenCalled()
      expect(view.container.textContent).toMatch(/JSON|数组/)
    },
  )
  it('expresses an explicit section clear as an empty collection and retains a false rewrite result', async () => {
    const view = await ready()
    const editor = jsonEditor(view)
    fill(editor, '{}')
    await act(async () => button(view.container, '保存词库').click())
    expect(api.updateGlossary).toHaveBeenCalledExactlyOnceWith('industrial_control', { glossary: {} })
    api.previewRewrite.mockResolvedValue({
      ruleset: 'industrial_control',
      original_query: 'no match',
      expanded_query: 'no match',
      changed: false,
    })
    await act(async () => button(view.container, '测试展开').click())
    expect(view.container.textContent).toContain('未命中词库中的术语')
  })
  it('retains failed save input and current server failure', async () => {
    const view = await ready()
    const editor = jsonEditor(view)
    fill(editor, '{"keep":["draft"]}')
    api.updateGlossary.mockRejectedValueOnce(new Error('write conflict'))
    await act(async () => button(view.container, '保存词库').click())
    expect(editor.value).toBe('{"keep":["draft"]}')
    expect(notices.error).toHaveBeenCalledWith(expect.stringContaining('write conflict'))
    expect(button(view.container, '保存词库').disabled).toBe(false)
  })
})
