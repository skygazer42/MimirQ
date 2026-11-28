// @vitest-environment happy-dom

import React, { type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { DocumentHealthCard } from '@/types/documents'

const query = vi.hoisted(() => ({ health: undefined as DocumentHealthCard | undefined }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ data: query.health, error: null, isPending: false, isFetching: false }),
}))
vi.mock('@/components/app-frame', () => ({ AppFrame: ({ children }: { children: ReactNode }) => <>{children}</> }))
vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))

import DocumentHealthPage from '@/components/knowledge/document-health-page'

function renderHealth(overrides: Partial<DocumentHealthCard> = {}) {
  query.health = {
    document_id: 'document-a',
    filename: '设备维护手册.pdf',
    file_type: 'pdf',
    status: 'completed',
    generated_at: '2026-11-23T12:00:00Z',
    parsing: { parser_backend: 'auto', parse_quality: { score: 0.86 }, page_count: null },
    chunking: { chunk_count: 8, total_characters: 24000 },
    ...overrides,
  }
  const container = document.createElement('div')
  container.innerHTML = renderToStaticMarkup(<DocumentHealthPage documentId="document-a" />)
  return container
}

function fact(container: HTMLElement, label: string) {
  const node = Array.from(container.querySelectorAll('section div')).find((element) => element.textContent === label)!
  return node.nextElementSibling!.textContent
}

describe('document health presentation', () => {
  it('shows one parse score and uses Chinese diagnostic labels', () => {
    const report = renderHealth()
    expect(report.textContent?.match(/0\.860/g)).toHaveLength(1)
    expect(report.textContent).not.toMatch(/Parse score|Overlap waste|trace|chunk|0\.8600/)
    expect(report.textContent).toContain('重叠冗余率')
    expect(report.textContent).toContain('扫描检索记录')
    expect(report.textContent).toContain('去重命中切片')
  })

  it('keeps missing collection and statistics distinct from real zeroes', () => {
    const report = renderHealth({
      kg: { summary: { entities: 0, relations: 0 } },
      retrieval_hits: {
        enabled: true,
        available: false,
        window_minutes: 1440,
        max_bytes: 0,
        truncated: false,
        traces_scanned: 0,
        traces_with_hits: 0,
        citations_matched: 0,
      },
    })
    expect(fact(report, '请求解析器')).toBe('—')
    expect(fact(report, '扫描件')).toBe('—')
    expect(fact(report, '页数')).toBe('—')
    expect(fact(report, '扫描检索记录')).toBe('—')
    expect(fact(report, '重叠冗余率')).toBe('—')
    expect(report.textContent?.match(/未采集|暂无统计/g)).toHaveLength(2)
    expect(report.textContent).toContain('“—” 表示未采集或暂无统计。')
    expect(report.textContent).not.toMatch(/尚无覆盖统计|覆盖 —|未评分/)
    expect(fact(report, '实体')).toBe('0')
    expect(fact(report, '关系')).toBe('0')
  })

  it('preserves collected zeroes and false values alongside missing values', () => {
    const report = renderHealth({
      parsing: { parser_backend: '', parse_quality: { score: 0 }, page_count: 0, is_scanned: false },
      chunking: { chunk_count: 0, total_characters: 0 },
      retrieval_hits: {
        enabled: true,
        available: true,
        window_minutes: 1440,
        max_bytes: 0,
        truncated: false,
        traces_scanned: 0,
        traces_with_hits: 0,
        citations_matched: 0,
        hit_rate: 0,
      },
    })
    expect(report.textContent).toContain('0.000')
    expect(fact(report, '解析器')).toBe('—')
    expect(fact(report, '页数')).toBe('0')
    expect(fact(report, '扫描件')).toBe('否')
    expect(fact(report, '切片数')).toBe('0')
    expect(fact(report, '总字符')).toBe('0')
    expect(fact(report, '命中率')).toBe('0.00%')
    expect(fact(report, '截断')).toBe('否')
  })

  it('uses consistent score precision and formats pronoun ratio as a percentage', () => {
    const report = renderHealth({
      chunking: {
        chunk_count: 8,
        total_characters: 24000,
        semantic_quality: {
          sampled_chunks: 8,
          needs_review: 0,
          needs_review_ratio: 0,
          mean_information_density: 0.812345,
          mean_semantic_completeness: 0.9,
          mean_self_containedness: null,
          mean_pronoun_ratio: 0.125,
        },
      },
    })
    expect(fact(report, '信息密度')).toBe('0.812')
    expect(fact(report, '语义完整')).toBe('0.900')
    expect(fact(report, '自包含')).toBe('—')
    expect(fact(report, '代词率')).toBe('12.5%')
  })
})
