// @vitest-environment happy-dom
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@/test/hook-harness'
import type { EvidenceRetrieveResponse } from '@/types'

const api = vi.hoisted(() => ({ retrieve: vi.fn() }))
vi.mock('@/lib/api', () => ({ ragApi: { retrieveEvidence: api.retrieve } }))
import { buildRetrieveDatasetScope, useRetrievalPreview } from './use-retrieval-preview'

const response = (text = '文档正文'): EvidenceRetrieveResponse => ({ schema: 'mimirq.evidence.v1', query_for_retrieval: '实际检索问题', has_evidence: true, abstain_triggered: false, citations: [{ document_id: 'doc-1', chunk_id: 'chunk-1', chunk_content: text }] })
const hooks: Array<{ unmount: () => void }> = []
function open(scope: () => string | undefined = () => 'team-a', ids: readonly string[] = ['team-a']) {
  const hook = renderHook(() => useRetrievalPreview(scope(), ids))
  hooks.push(hook)
  return hook
}

describe('retrieval console requests', () => {
  beforeEach(() => { vi.clearAllMocks(); api.retrieve.mockResolvedValue(response()) })
  afterEach(() => { hooks.splice(0).forEach(hook => hook.unmount()) })

  it('uses the chosen dataset or deduplicated accessible scope', () => {
    expect(buildRetrieveDatasetScope(' team-a ', ['team-b'])).toEqual({ dataset_id: 'team-a' })
    expect(buildRetrieveDatasetScope(null, [' team-a ', '', 'team-a', 'team-b'])).toEqual({ dataset_ids: ['team-a', 'team-b'] })
    expect(buildRetrieveDatasetScope(undefined, [])).toEqual({})
  })

  it('inherits saved settings without diagnostic profile or frontend parameter overrides', async () => {
    const hook = open(() => undefined, ['team-a', 'team-b'])
    act(() => hook.result.current.setDraft('  如何管理权限？  '))
    await act(async () => { await hook.result.current.search() })
    expect(api.retrieve).toHaveBeenCalledExactlyOnceWith({ query: '如何管理权限？', dataset_ids: ['team-a', 'team-b'], rag_config: {} })
    expect(hook.result.current.run?.hits).toHaveLength(1)
    expect(hook.result.current.history).toHaveLength(1)
    expect(hook.result.current.run?.queryForRetrieval).toBe('实际检索问题')
  })

  it('blocks empty and duplicate submissions while keeping an editable draft', async () => {
    const hook = open()
    await act(async () => { await hook.result.current.search() })
    expect(api.retrieve).not.toHaveBeenCalled()
    let release!: (value: EvidenceRetrieveResponse) => void
    api.retrieve.mockReturnValue(new Promise(resolve => { release = resolve }))
    act(() => hook.result.current.setDraft('权限'))
    let pending!: Promise<void>
    act(() => { pending = hook.result.current.search(); void hook.result.current.search() })
    expect(api.retrieve).toHaveBeenCalledTimes(1)
    expect(hook.result.current.isSearching).toBe(true)
    act(() => hook.result.current.setDraft('新的问题'))
    await act(async () => { release(response()); await pending })
    expect(hook.result.current.draft).toBe('新的问题')
    expect(hook.result.current.run?.query).toBe('权限')
  })

  it('ignores late responses after scope changes and preserves the question', async () => {
    let scope = 'team-a'
    const hook = open(() => scope)
    let release!: (value: EvidenceRetrieveResponse) => void
    api.retrieve.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
    act(() => hook.result.current.setDraft('权限'))
    let pending!: Promise<void>
    act(() => { pending = hook.result.current.search() })
    scope = 'team-b'; hook.rerender()
    expect(hook.result.current.isSearching).toBe(false)
    expect(hook.result.current.run).toBeNull()
    await act(async () => { release(response('旧范围')); await pending })
    expect(hook.result.current.run).toBeNull()
    expect(hook.result.current.history).toHaveLength(0)
    expect(hook.result.current.draft).toBe('权限')
    await act(async () => { await hook.result.current.search() })
    expect(api.retrieve).toHaveBeenLastCalledWith({ query: '权限', dataset_id: 'team-b', rag_config: {} })
  })

  it('retains the failed question for retry and does not fabricate history', async () => {
    const hook = open()
    api.retrieve.mockRejectedValueOnce(new Error('temporarily unavailable'))
    act(() => hook.result.current.setDraft('权限'))
    await act(async () => { await hook.result.current.search() })
    expect(hook.result.current.error).toContain('temporarily unavailable')
    expect(hook.result.current.draft).toBe('权限')
    expect(hook.result.current.history).toHaveLength(0)
    await act(async () => { await hook.result.current.search() })
    expect(hook.result.current.error).toBeNull()
    expect(hook.result.current.history).toHaveLength(1)
  })

  it('restores real runs without a new request and can clear history while reading', async () => {
    const hook = open()
    act(() => hook.result.current.setDraft('第一个问题'))
    await act(async () => { await hook.result.current.search() })
    const first = hook.result.current.run!
    act(() => hook.result.current.setDraft('第二个问题'))
    await act(async () => { await hook.result.current.search() })
    act(() => hook.result.current.restore(first))
    expect(api.retrieve).toHaveBeenCalledTimes(2)
    expect(hook.result.current.draft).toBe('第一个问题')
    expect(hook.result.current.run).toEqual(first)
    act(() => hook.result.current.clearHistory())
    expect(hook.result.current.history).toHaveLength(0)
    expect(hook.result.current.run).toEqual(first)
  })
})
