import { describe, expect, it } from 'vitest'
import type { ChatCostUsageSummary, ChatTokenQuotaStatus, ChatTokenUsageSummary, TenantQuotaSummary } from '@/types'
import { averageRetrievalMs, buildQuotaReadings, buildUsageRows, formatCount, formatDuration, parseUsageLocation } from './usage-model'

const summary: ChatTokenUsageSummary = {
  window_start: '2026-10-18T10:00:00Z', window_end: '2026-10-25T10:00:00Z',
  total_assistant_messages: 10, total_assistant_tokens: 100,
  by_dataset: [
    { dataset_id: 'known', assistant_messages: 6, assistant_tokens: 60 },
    { dataset_id: 'hidden', assistant_messages: 4, assistant_tokens: 40 },
    { dataset_id: null, assistant_messages: 0, assistant_tokens: 0 },
  ],
}
const cost: ChatCostUsageSummary = {
  window_start: summary.window_start, window_end: summary.window_end,
  total_assistant_messages: 5, total_llm_prompt_tokens: 110, total_llm_completion_tokens: 40,
  total_llm_total_tokens: 150, total_embedding_query_tokens: 20, total_embedding_query_chars: 60,
  total_retrieval_elapsed_sec: 1, total_rerank_elapsed_sec: .1,
  by_dataset: ['known', 'cost-only'].map((id, index) => ({ dataset_id: id, assistant_messages: index ? 3 : 2,
    llm_prompt_tokens: index ? 30 : 80, llm_completion_tokens: 20, llm_total_tokens: index ? 50 : 100,
    embedding_query_tokens: 10, embedding_query_chars: 30, retrieval_elapsed_sec_sum: .5, rerank_elapsed_sec_sum: .05 })),
}
const chat: ChatTokenQuotaStatus = { enabled: true, mode: 'block', used: 90, limit: 100, remaining: 10,
  exceeded: false, window_hours: 6, window_start: '2026-10-25T04:00:00Z', window_end: '2026-10-25T10:00:00Z' }
const tenant: TenantQuotaSummary = {
  documents: { enabled: false, used: 0, limit: 0, remaining: 0, exceeded: false },
  storage: { enabled: true, used_bytes: 1024, limit_bytes: 2048, remaining_bytes: 1024, exceeded: false },
  embedding_chars: { enabled: true, mode: 'warn', used_chars: 20, limit_chars: 200, remaining_chars: 180,
    exceeded: false, window_hours: 48, window_start: '2026-10-23T10:00:00Z', window_end: chat.window_end },
  qps: { enabled: true, mode: 'block', rps: 10, burst: 20, scopes: ['chat', 'retrieval'] },
}

describe('usage overview data boundaries', () => {
  it('restores only supported statistics scopes from navigation history', () => {
    expect(parseUsageLocation('?window_days=30&view=resources&page=2')).toEqual({ windowDays: 30, view: 'resources', page: 2 })
    expect(parseUsageLocation('?window_days=3&view=unknown&page=-2')).toEqual({ windowDays: 7, view: 'attribution', page: 1 })
    expect(parseUsageLocation('?page=Infinity')).toEqual({ windowDays: 7, view: 'attribution', page: 1 })
  })
  it('keeps both APIs attribution rows without confusing LLM and assistant tokens', () => {
    const rows = buildUsageRows(summary, cost, { known: '工程文档库' }, 'ready')
    expect(rows).toHaveLength(4)
    expect(rows.find(r => r.datasetId === 'known')).toMatchObject({ name: '工程文档库', assistantTokens: 60, messages: 6, share: 60, visibility: 'available' })
    expect(rows.find(r => r.datasetId === 'cost-only')).toMatchObject({ assistantTokens: null, share: null, messages: 3 })
    expect(rows.find(r => r.datasetId === 'known')?.cost?.llm_total_tokens).toBe(100)
  })

  it('distinguishes confirmed hidden and unbound rows from failed name loading', () => {
    const confirmed = buildUsageRows(summary, cost, {}, 'ready')
    expect(confirmed.find(r => r.datasetId === 'hidden')).toMatchObject({ visibility: 'hidden', href: null })
    expect(confirmed.find(r => r.datasetId === null)).toMatchObject({ visibility: 'unbound', href: null })
    const unresolved = buildUsageRows(summary, cost, {}, 'error')
    expect(unresolved.find(r => r.datasetId === 'hidden')).toMatchObject({ visibility: 'unresolved', href: null })
    expect(unresolved.find(r => r.datasetId === 'hidden')?.name).not.toBe('不可见数据集')
  })

  it('encodes the actual dataset destination and retains zero instead of inventing missing use', () => {
    const rows = buildUsageRows(summary, null, { known: '资料库' }, 'ready')
    expect(rows[0].href).toBe('/knowledge?dataset=known&lifecycle=all&status=all')
    expect(rows.find(r => r.datasetId === null)?.assistantTokens).toBe(0)
    expect(buildUsageRows(null, cost, {}, 'pending')[0].assistantTokens).toBeNull()
  })

  it('does not divide by zero or turn unavailable durations into zero', () => {
    expect(averageRetrievalMs(.5, 2)).toBe(250)
    expect(averageRetrievalMs(0, 2)).toBe(0)
    expect(averageRetrievalMs(1, 0)).toBeNull()
    expect(formatCount(undefined)).toBe('—')
    expect(formatCount(0)).toBe('0')
    expect(formatDuration(null)).toBe('—')
    expect(formatDuration(0)).toBe('0 ms')
  })

  it('keeps each quota window independent and rate config free of utilization', () => {
    const readings = buildQuotaReadings(chat, tenant)
    expect(readings.find(q => q.key === 'chat')).toMatchObject({ windowHours: 6, percentage: 90, used: 90 })
    expect(readings.find(q => q.key === 'embedding')).toMatchObject({ windowHours: 48, percentage: 10, mode: 'warn' })
    expect(readings.find(q => q.key === 'storage')).toMatchObject({ scope: '当前占用', percentage: 50 })
    expect(readings.find(q => q.key === 'qps')).toMatchObject({ percentage: null, progress: null, scopes: ['聊天', '检索'] })
  })

  it('does not show disabled and unavailable quotas as exhausted resources', () => {
    expect(buildQuotaReadings(chat, tenant).find(q => q.key === 'documents')).toMatchObject({ enabled: false, percentage: null, remaining: null })
    expect(buildQuotaReadings(null, null).every(q => q.enabled === null && q.percentage === null)).toBe(true)
    const exceeded = buildQuotaReadings({ ...chat, used: 120, remaining: 0, exceeded: true }, tenant)[0]
    expect(exceeded).toMatchObject({ percentage: 120, progress: 100, remaining: 0, tone: 'danger' })
  })
})
