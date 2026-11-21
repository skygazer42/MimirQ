// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SuiteDashboardDialog } from './suite-dashboard-dialog'
import { HardcaseCandidatesDialog } from './hardcase-candidates-dialog'
import { parseSuiteDashboard } from '@/lib/evidence-dashboard'
import { parseHardcaseDiscovery } from '@/lib/evidence-hardcases'

vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))

const cleanups: Array<() => void> = []
function mount(element: React.ReactElement) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  act(() => root.render(element))
  cleanups.push(() => {
    act(() => root.unmount())
    container.remove()
  })
  return (next: React.ReactElement) => act(() => root.render(next))
}
function dialog() {
  const element = document.querySelector<HTMLElement>('[role="dialog"]')
  if (element === null) throw new Error('Dialog did not mount')
  return element
}
function dashboardSnapshot() {
  const duration = { count: 0, p50_sec: null, p90_sec: 0, mean_sec: 0.25 }
  return {
    includeArchived: false,
    data: parseSuiteDashboard({
      generated_at: '2026-11-16T00:00:00Z',
      throughput: {
        window_days: 7,
        last_window: { created: 0, reviewed: 0, approved: 0 },
        draft_to_reviewed: duration,
        reviewed_to_approved: duration,
        draft_to_approved: duration,
      },
      coverage: {
        language: [],
        file_type: [],
        quality_bucket: [],
        channel: [],
        heatmaps: { language_x_file_type: { x: ['pdf'], y: ['zh'], z: [[0]], metric: 'items' } },
      },
    }),
  }
}
function hardcaseSnapshot(version: number | null) {
  return {
    maxRating: 2,
    maxCandidates: 50,
    includeExisting: false,
    data: parseHardcaseDiscovery({
      generated_at: '2026-11-16T00:00:00Z',
      enabled: true,
      window_minutes: 10080,
      max_bytes: 100000,
      truncated: false,
      feedback_scanned: 1,
      trace_index_size: 1,
      candidates: [
        {
          question_hash: 'hash',
          cluster_size: 0,
          feedback_ids: ['feedback'],
          request_ids: [],
          retrieval_error_kinds: {},
          citations_count: 0,
          rag_config_template: { template_key: 'policy', version },
        },
      ],
    }),
  }
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})
afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
  document.body.innerHTML = ''
})

describe('evidence diagnostic presentation through actual dialogs', () => {
  it('keeps zero durations and cells distinct from unknown values while retaining a refreshing dashboard', () => {
    const props = {
      open: true,
      selectedSuite: null,
      selectedSuiteId: 'suite',
      includeArchived: false,
      loading: false,
      error: null,
      snapshot: dashboardSnapshot(),
      onOpenChange: vi.fn(),
      onIncludeArchivedChange: vi.fn(),
      onRefresh: vi.fn(),
    }
    const render = mount(<SuiteDashboardDialog {...props} />)
    expect(dialog().textContent).toContain('p50 未提供')
    expect(dialog().textContent).toContain('p90 0s')
    expect(dialog().textContent).toContain('mean 0.25s')
    const table = dialog().querySelector('table')
    expect(table?.querySelector('td')?.textContent).toBe('0')
    expect(table?.querySelector('th[scope="row"]')?.textContent).toBe('zh')
    render(<SuiteDashboardDialog {...props} loading />)
    expect(dialog().querySelector('td')?.textContent).toBe('0')
    render(<SuiteDashboardDialog {...props} includeArchived error="读取失败" />)
    expect(dialog().querySelector('[role="alert"]')?.textContent).toContain('读取失败')
    expect(dialog().textContent).toContain('当前统计：不含已归档条目')
  })

  it('renders a null template version without manufacturing version zero', () => {
    const props = {
      open: true,
      selectedSuiteId: 'suite',
      loading: false,
      error: null,
      snapshot: hardcaseSnapshot(null),
      maxRating: 2,
      includeExisting: false,
      maxCandidates: 50,
      tags: [],
      convertingFeedbackIds: new Set<string>(),
      feedbackErrors: new Map<string, string>(),
      onOpenChange: vi.fn(),
      onMaxRatingChange: vi.fn(),
      onIncludeExistingChange: vi.fn(),
      onMaxCandidatesChange: vi.fn(),
      onTagsChange: vi.fn(),
      onRefresh: vi.fn(),
      onCopyText: vi.fn(),
      onConvertFeedback: vi.fn(),
    }
    const render = mount(<HardcaseCandidatesDialog {...props} />)
    expect(dialog().textContent).toContain('cites 0')
    expect(dialog().textContent).toContain('cluster 0')
    expect(dialog().textContent).not.toContain('version 0')
    render(<HardcaseCandidatesDialog {...props} snapshot={hardcaseSnapshot(0)} />)
    expect(dialog().textContent).toContain('version 0')
    expect(dialog().querySelector('label[for="evidence-hardcase-tags"]')).not.toBeNull()
    expect(dialog().querySelector('input#evidence-hardcase-tags')).not.toBeNull()
  })

  it('shows first-load feedback without telling the user that no candidates were found', () => {
    mount(
      <HardcaseCandidatesDialog
        open
        selectedSuiteId="suite"
        loading
        error={null}
        snapshot={null}
        maxRating={2}
        includeExisting={false}
        maxCandidates={50}
        tags={[]}
        convertingFeedbackIds={new Set()}
        feedbackErrors={new Map()}
        onOpenChange={vi.fn()}
        onMaxRatingChange={vi.fn()}
        onIncludeExistingChange={vi.fn()}
        onMaxCandidatesChange={vi.fn()}
        onTagsChange={vi.fn()}
        onRefresh={vi.fn()}
        onCopyText={vi.fn()}
        onConvertFeedback={vi.fn()}
      />,
    )
    expect(dialog().querySelector('[role="status"]')?.getAttribute('aria-label')).toBe('正在读取候选')
    expect(dialog().textContent).not.toContain('暂无候选')
  })

  it('validates conversion tags independently of query controls and dispatches the selected feedback identity', () => {
    const convert = vi.fn()
    const copy = vi.fn()
    function Candidates() {
      const [tags, setTags] = React.useState<string[]>([])
      return (
        <HardcaseCandidatesDialog
          open
          selectedSuiteId="suite"
          loading={false}
          error={null}
          snapshot={hardcaseSnapshot(0)}
          maxRating={2}
          includeExisting={false}
          maxCandidates={50}
          tags={tags}
          convertingFeedbackIds={new Set()}
          feedbackErrors={new Map()}
          onOpenChange={vi.fn()}
          onMaxRatingChange={vi.fn()}
          onIncludeExistingChange={vi.fn()}
          onMaxCandidatesChange={vi.fn()}
          onTagsChange={setTags}
          onRefresh={vi.fn()}
          onCopyText={copy}
          onConvertFeedback={convert}
        />
      )
    }
    mount(<Candidates />)
    const input = dialog().querySelector<HTMLInputElement>('#evidence-hardcase-tags')!
    const type = (value: string) =>
      act(() => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
        input.dispatchEvent(new Event('input', { bubbles: true }))
      })
    const button = Array.from(dialog().querySelectorAll<HTMLButtonElement>('button')).find(
      (element) => element.textContent === '转为 draft',
    )!
    type('x'.repeat(65))
    act(() => button.click())
    expect(convert).not.toHaveBeenCalled()
    expect(input.value).toBe('x'.repeat(65))
    type('')
    act(() => dialog().querySelector<HTMLButtonElement>('button[aria-label="复制 feedback_id"]')!.click())
    expect(copy).toHaveBeenCalledExactlyOnceWith('feedback_id', 'feedback')
    expect(convert).not.toHaveBeenCalled()
    act(() => button.click())
    expect(convert).toHaveBeenCalledExactlyOnceWith('feedback', 'hash')
  })
})
