import { describe, expect, it } from 'vitest'
import { parseSuiteDashboard } from './evidence-dashboard'

function dashboard() {
  const leadTime = { count: 0, p50_sec: null, p90_sec: 0, mean_sec: 0.25 }
  return {
    generated_at: '2026-11-16T00:00:00Z',
    throughput: {
      window_days: 7,
      last_window: { created: 0, reviewed: 0, approved: 0 },
      draft_to_reviewed: leadTime,
      reviewed_to_approved: leadTime,
      draft_to_approved: leadTime,
    },
    coverage: {
      language: [],
      file_type: [],
      quality_bucket: [],
      channel: [],
      heatmaps: { language_x_file_type: { x: ['pdf'], y: ['zh'], z: [[0]], metric: 'items' } },
    },
    extra: { kept: false },
  }
}

describe('evidence dashboard response', () => {
  it('preserves zero, unknown durations and opaque response fields', () => {
    const source = dashboard()
    expect(parseSuiteDashboard(source)).toEqual(source)
  })
  it.each([null, '', false, '1'])('does not coerce an invalid event count %j to zero', (created) => {
    const source = dashboard()
    expect(() =>
      parseSuiteDashboard({
        ...source,
        throughput: { ...source.throughput, last_window: { ...source.throughput.last_window, created } },
      }),
    ).toThrow()
  })
  it('rejects missing table cells instead of displaying them as zero', () => {
    const source = dashboard()
    source.coverage.heatmaps.language_x_file_type.z = [[]]
    expect(() => parseSuiteDashboard(source)).toThrow('行列')
  })
  it('rejects a missing row instead of showing a partial heatmap', () => {
    const source = dashboard()
    source.coverage.heatmaps.language_x_file_type.z = []
    expect(() => parseSuiteDashboard(source)).toThrow('行列')
  })
  it('rejects an incomplete successful HTTP object rather than manufacturing an empty dashboard', () => {
    expect(() => parseSuiteDashboard({ generated_at: '' })).toThrow()
  })
})
