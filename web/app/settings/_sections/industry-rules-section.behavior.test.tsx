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

describe('industry rules read ownership', () => {
  it('allows a new explicit load after idle cache clear without rendering or editing first', async () => {
    const view = await mount()
    await waitForAssertion(() => expect(button(view.container, 'industrial_control')).toBeDefined())
    const key = queryKeys.industryRules.ruleset('industrial_control')
    const previous = view.client.getQueryCache().find({ queryKey: key, exact: true })
    expect(previous).toBeDefined()
    act(() => view.client.clear())
    expect(view.client.getQueryCache().find({ queryKey: key, exact: true })).toBeUndefined()

    await act(async () => button(view.container, '载入').click())

    expect(api.getRuleset).toHaveBeenCalledOnce()
    expect(JSON.parse(view.container.querySelectorAll('textarea')[0].value)).toEqual(detail().ruleset.glossary)
    expect(view.client.getQueryCache().find({ queryKey: key, exact: true })).not.toBe(previous)
  })

  it('allows a new explicit index refresh after idle cache clear without another render', async () => {
    api.listRulesets.mockResolvedValueOnce({ schema: 'mimirq.industry_rules_index.v1', count: 0, rulesets: [] })
    const view = await mount()
    await waitForAssertion(() => expect(button(view.container, '获取规则集').disabled).toBe(false))
    act(() => view.client.clear())
    expect(
      view.client.getQueryCache().find({ queryKey: queryKeys.industryRules.rulesets, exact: true }),
    ).toBeUndefined()

    await act(async () => button(view.container, '获取规则集').click())

    expect(api.listRulesets).toHaveBeenCalledTimes(2)
    await waitForAssertion(() => expect(button(view.container, 'industrial_control')).toBeDefined())
  })

  it.each(['preview', 'patterns'] as const)(
    'allows a fresh %s after idle clear without triggering a detail fetch',
    async (action) => {
      api.previewRewrite.mockResolvedValueOnce({
        schema: 'mimirq.industry_rules_preview.v1',
        ruleset: 'industrial_control',
        original_query: 'PLC 报警如何排查？',
        expanded_query: 'PLC 报警如何排查？',
        changed: false,
      })
      const view = await mount()
      await waitForAssertion(() => expect(button(view.container, 'industrial_control')).toBeDefined())
      act(() => view.client.clear())

      await act(async () => button(view.container, action === 'preview' ? '预览' : '保存规则').click())

      expect(action === 'preview' ? api.previewRewrite : api.updatePatterns).toHaveBeenCalledOnce()
      expect(api.getRuleset).not.toHaveBeenCalled()
      expect(notices.success).toHaveBeenCalledOnce()
    },
  )

  it('keeps a removed in-flight save retired without manually rendering after clear', async () => {
    const pending = deferred<{ schema: string; ruleset: string; section: string; updated_count: number }>()
    api.updatePatterns.mockReturnValueOnce(pending.promise)
    const view = await mount()
    act(() => button(view.container, '保存规则').click())
    await waitForAssertion(() => expect(api.updatePatterns).toHaveBeenCalledOnce())
    const key = queryKeys.industryRules.ruleset('industrial_control')
    const previous = view.client.getQueryCache().find({ queryKey: key, exact: true })
    act(() => view.client.clear())
    await act(async () =>
      pending.resolve({
        schema: 'mimirq.industry_rules_update.v1',
        ruleset: 'industrial_control',
        section: 'patterns',
        updated_count: 0,
      }),
    )
    await waitForAssertion(() => expect(button(view.container, '保存规则').disabled).toBe(false))

    expect(view.client.getQueryCache().find({ queryKey: key, exact: true })).not.toBe(previous)
    expect(view.client.getQueryState(key)?.isInvalidated).toBe(false)
    expect(notices.success).not.toHaveBeenCalled()
    expect(notices.error).not.toHaveBeenCalled()
  })

  it('does not replace another ruleset draft when an earlier load resolves', async () => {
    const old = deferred<ReturnType<typeof detail>>()
    api.getRuleset.mockReturnValueOnce(old.promise)
    const view = await mount()
    act(() => button(view.container, '载入').click())
    await waitForAssertion(() => expect(api.getRuleset).toHaveBeenCalledWith('industrial_control'))
    fill(view.container.querySelector<HTMLInputElement>('#industry-rules-name')!, 'other-ruleset')
    const glossary = view.container.querySelectorAll('textarea')[0]
    fill(glossary, '{"new-draft":["keep"]}')

    await act(async () => old.resolve(detail()))
    await waitForAssertion(() => expect(button(view.container, '载入').disabled).toBe(false))

    expect(glossary.value).toBe('{"new-draft":["keep"]}')
    expect(notices.success).not.toHaveBeenCalled()
    expect(view.client.getQueryData(queryKeys.industryRules.ruleset('industrial_control'))).toEqual(detail())
  })

  it('preserves an editor changed while its own load is still pending', async () => {
    const pending = deferred<ReturnType<typeof detail>>()
    api.getRuleset.mockReturnValueOnce(pending.promise)
    const view = await mount()
    act(() => button(view.container, '载入').click())
    await waitForAssertion(() => expect(api.getRuleset).toHaveBeenCalledOnce())
    fill(view.container.querySelectorAll('textarea')[0], '{"typed-while-loading":["keep"]}')

    await act(async () => pending.resolve(detail()))
    await waitForAssertion(() => expect(button(view.container, '载入').disabled).toBe(false))

    expect(view.container.querySelectorAll('textarea')[0].value).toBe('{"typed-while-loading":["keep"]}')
    expect(JSON.parse(view.container.querySelectorAll('textarea')[1].value)).toEqual(detail().ruleset.patterns)
  })

  it('does not fabricate a successful empty load after the originating query is removed', async () => {
    const pending = deferred<ReturnType<typeof detail>>()
    api.getRuleset.mockReturnValueOnce(pending.promise)
    const view = await mount()
    act(() => button(view.container, '载入').click())
    await waitForAssertion(() => expect(api.getRuleset).toHaveBeenCalledOnce())
    act(() => view.client.clear())
    await view.render()
    await act(async () => pending.resolve(detail()))

    expect(notices.success).not.toHaveBeenCalled()
    expect(view.container.textContent).toContain('载入规则、运行预览或保存后')
  })

  it.each(['resolve', 'reject'] as const)('does not publish a load %s after unmount', async (outcome) => {
    const pending = deferred<ReturnType<typeof detail>>()
    api.getRuleset.mockReturnValueOnce(pending.promise)
    const view = await mount()
    act(() => button(view.container, '载入').click())
    await waitForAssertion(() => expect(api.getRuleset).toHaveBeenCalledOnce())
    view.unmount()
    await act(async () => {
      if (outcome === 'resolve') pending.resolve(detail())
      else pending.reject(new Error('retired read failed'))
    })
    expect(notices.success).not.toHaveBeenCalled()
    expect(notices.error).not.toHaveBeenCalled()
  })

  it('does not publish or invalidate a retired save after a silent same-account login', async () => {
    const pending = deferred<{ schema: string; ruleset: string; section: string; updated_count: number }>()
    api.updatePatterns.mockReturnValueOnce(pending.promise)
    const view = await mount()
    act(() => button(view.container, '保存规则').click())
    await waitForAssertion(() => expect(api.updatePatterns).toHaveBeenCalledOnce())
    act(() => setAuthSession({ token, user: profile }))
    await act(async () =>
      pending.resolve({
        schema: 'mimirq.industry_rules_update.v1',
        ruleset: 'industrial_control',
        section: 'patterns',
        updated_count: 0,
      }),
    )

    expect(notices.success).not.toHaveBeenCalled()
    expect(view.client.getQueryState(queryKeys.industryRules.ruleset('industrial_control'))?.isInvalidated).toBe(false)
  })
})

describe('industry rules exact section writes', () => {
  it('sends only the selected section and preserves nested false, zero and null options', async () => {
    const view = await mount()
    const patterns = [
      { id: 'custom', enabled: false, weight: 0, optional: null, nested: { enabled: false, score: 0, data: null } },
    ]
    fill(view.container.querySelectorAll('textarea')[1], JSON.stringify(patterns))
    await act(async () => button(view.container, '保存规则').click())
    expect(api.updatePatterns).toHaveBeenCalledExactlyOnceWith('industrial_control', { patterns })
    expect(api.updateGlossary).not.toHaveBeenCalled()
    expect(api.updateIntents).not.toHaveBeenCalled()
  })

  it('keeps malformed JSON visible and never calls the write API for it', async () => {
    const view = await mount()
    const editor = view.container.querySelectorAll('textarea')[1]
    fill(editor, '{invalid')
    await act(async () => button(view.container, '保存规则').click())
    expect(api.updatePatterns).not.toHaveBeenCalled()
    expect(notices.error).toHaveBeenCalledOnce()
    expect(editor.value).toBe('{invalid')
  })

  it('retains explicit invalid null for the existing API failure rather than silently defaulting it', async () => {
    api.updateGlossary.mockRejectedValueOnce(new Error('glossary must be an object'))
    const view = await mount()
    const editor = view.container.querySelectorAll('textarea')[0]
    fill(editor, 'null')
    await act(async () => button(view.container, '保存词库').click())
    expect(api.updateGlossary).toHaveBeenCalledWith('industrial_control', { glossary: null })
    expect(notices.error).toHaveBeenCalledWith('glossary must be an object')
    expect(editor.value).toBe('null')
  })

  it('retains empty-editor clear semantics and a false rewrite result', async () => {
    api.previewRewrite.mockResolvedValueOnce({
      schema: 'mimirq.industry_rules_preview.v1',
      ruleset: 'industrial_control',
      original_query: 'PLC 报警如何排查？',
      expanded_query: 'PLC 报警如何排查？',
      changed: false,
    })
    const view = await mount()
    fill(view.container.querySelectorAll('textarea')[2], '')
    await act(async () => button(view.container, '保存意图').click())
    expect(api.updateIntents).toHaveBeenCalledWith('industrial_control', { intents: [] })
    await waitForAssertion(() => expect(button(view.container, '预览').disabled).toBe(false))
    await act(async () => button(view.container, '预览').click())
    expect(view.container.textContent).toContain('未产生改写')
  })
})
