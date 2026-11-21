import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ParsedFileData } from '@/store/use-parsed-files-store'

const requests = vi.hoisted(() => ({ getParsedContent: vi.fn() }))

vi.mock('@/lib/api/documents', () => ({ documentApi: requests }))
vi.mock('@/lib/doc-content-cache', () => ({ getDocContentFromCache: async () => null }))

import { loadParsingLibraryContent } from './parsing-library-content'

describe('saved knowledge parsing quality', () => {
  beforeEach(() => {
    requests.getParsedContent.mockReset()
  })

  it('restores the actual quality and enhancement failure from document metadata', async () => {
    const quality = {
      score: 0,
      text_quality_score: 0,
      format_consistency_score: 0,
      table_quality_score: 0,
      reading_order_score: null,
      is_scanned: false,
      page_count: 1,
    }
    const gate = {
      grade: 'pass',
      reasons: [],
      evidence: { image_ocr: { error: 'image_unavailable' } },
    }
    requests.getParsedContent.mockResolvedValue({
      available: true,
      markdown_content: 'Saved body',
      original_markdown_content: 'Saved body',
      persisted_meta: { pdf_quality: quality, quality_gate: gate },
    })
    const file: ParsedFileData = {
      id: 'knowledge-quality',
      filename: 'saved.pdf',
      fileType: 'pdf',
      fileSize: 1,
      markdownContent: '',
      parsedAt: '2026-11-17T00:00:00Z',
      parser: 'pdf',
      source: 'knowledge_base',
      status: 'parsed',
    }

    const result = await loadParsingLibraryContent(file)
    expect(result.content?.pdfQuality).toEqual(quality)
    expect(result.content?.qualityGate).toEqual(gate)
  })
})
