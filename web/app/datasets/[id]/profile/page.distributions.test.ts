import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('dataset profile page distributions', () => {
  it('renders parse quality / language / pages sections', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('解析质量')
    expect(src).toContain('语言分布')
    expect(src).toContain('页数分布')
    expect(src).toContain('Chunk 数分布')
    expect(src).toContain('平均 Chunk 长度')
    expect(src).toContain('Chunk Targets')
    expect(src).toContain('Parsing provenance')

    // Ensure we wire the new summary fields into the page (not just headings).
    expect(src).toContain('parse_quality_histogram')
    expect(src).toContain('language_mix')
    expect(src).toContain('page_number_histogram')
    expect(src).toContain('chunk_count_histogram')
    expect(src).toContain('avg_chunk_chars_histogram')
    expect(src).toContain('chunk_targets')
    expect(src).toContain('parsing_provenance')
  })
})
