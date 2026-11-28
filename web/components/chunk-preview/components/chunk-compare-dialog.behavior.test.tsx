// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChunkPreviewResponse, ChunkPreviewStats } from '@/types'
import type { ChunkPreviewState } from '../types'

vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))

import { ChunkCompareDialog } from './chunk-compare-dialog'

const roots: Root[] = []

function preview(unit: 'chars' | 'tokens', stats?: ChunkPreviewStats | null): ChunkPreviewResponse {
  return {
    filename: 'same.md',
    file_type: 'md',
    file_size: 10,
    total_chunks: 1,
    total_characters: 4,
    params: { chunk_size: 500, chunk_overlap: 0, unit },
    chunks: [{ index: 0, content: 'text', length: 4, start_index: 0, end_index: 4 }],
    parser_backend: 'auto',
    chunk_strategy: 'recursive',
    stats,
  }
}

function run(id: string, fileId: string, cacheKey: string, createdAt: number): ChunkPreviewState['runHistory'][number] {
  return {
    id,
    fileId,
    fileName: 'same.md',
    parserBackend: 'auto',
    strategy: 'recursive',
    chunkSize: 500,
    chunkOverlap: 0,
    totalChunks: 1,
    durationMs: 10,
    createdAt,
    cacheHit: false,
    cacheKey,
  }
}

function mount(
  baseline: ChunkPreviewResponse | null,
  current: ChunkPreviewResponse,
  history?: ChunkPreviewState['runHistory'],
) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.push(root)
  const cached = vi.fn((key: string) => (key === 'baseline' ? baseline : current))
  const records = history ?? [run('new', 'file-current', 'current', 2), run('old', 'file-current', 'baseline', 1)]
  act(() =>
    root.render(
      <ChunkCompareDialog
        open
        onOpenChange={vi.fn()}
        current={current}
        currentFileId="file-current"
        currentFileName="same.md"
        runHistory={records}
        getCachedPreview={cached}
      />,
    ),
  )
  return { cached }
}

function region(label: string) {
  const element = document.querySelector<HTMLElement>(`section[aria-label="${label}"]`)
  if (element === null) throw new Error(`Missing statistics region ${label}`)
  return element
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})

afterEach(() => {
  for (const root of roots.splice(0)) act(() => root.unmount())
  document.body.replaceChildren()
})

describe('actual comparison statistics and candidate ownership', () => {
  it('shows an unavailable cached baseline without substituting an empty comparison', () => {
    mount(null, preview('chars'))
    expect(document.body.textContent).toContain('compareDialog.baselineUnavailable')
    expect(document.querySelector('section[aria-label="compareDialog.cards.lengthDistribution"]')).toBeNull()
  })

  it('does not display zero changes when either statistic is missing', () => {
    mount(preview('chars', null), preview('chars'))
    expect(region('compareDialog.cards.lengthDistribution').textContent).not.toMatch(/\(0\)/)
    expect(region('compareDialog.cards.qualityOverview').textContent).not.toMatch(/\(0(?:%)?\)/)
  })

  it('keeps actual zero changes visible', () => {
    const stats = {
      unit: 'chars' as const,
      p10: 0,
      avg: 0,
      p95: 0,
      coverage_ratio: 0,
      overlap_waste_ratio: 0,
      gap_count: 0,
    }
    mount(preview('chars', stats), preview('chars', stats))
    expect(region('compareDialog.cards.lengthDistribution').textContent).toContain('(0)')
    expect(region('compareDialog.cards.qualityOverview').textContent).toContain('(0%)')
  })

  it('explains incomparable units and omits their fabricated length delta', () => {
    mount(
      preview('chars', { unit: 'chars', avg: 100, p10: 80, p95: 120 }),
      preview('tokens', { unit: 'tokens', avg: 7, p10: 5, p95: 9 }),
    )
    const text = region('compareDialog.cards.lengthDistribution').textContent
    expect(text).toContain('A: 100 / B: 7')
    expect(text).toContain('compareDialog.incompatibleLengthUnits')
    expect(text).not.toContain('(-93)')
  })

  it('does not use another file with the same name as a comparison baseline', () => {
    mount(preview('chars'), preview('chars'), [
      run('new', 'file-current', 'current', 2),
      run('foreign', 'other-file', 'baseline', 1),
    ])
    expect(document.body.textContent).toContain('compareDialog.needTwoRuns')
  })

  it('does not count two history records pointing to the same cache result as two variants', () => {
    mount(preview('chars'), preview('chars'), [
      run('new', 'file-current', 'current', 2),
      run('old', 'file-current', 'current', 1),
    ])
    expect(document.body.textContent).toContain('compareDialog.needTwoRuns')
  })
})
