import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('pipeline options panel typography', () => {
  it('keeps numeric option rows on the settings typography scale', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pipeline-options-panel.tsx'), 'utf8')

    expect(src).toContain('const numberFieldLabelClass =')
    expect(src).toContain("'flex items-center justify-between gap-2 text-[11px] font-medium leading-4 text-muted-foreground'")
    expect(src).toContain('const numberFieldLabelTextClass =')
    expect(src).toContain("'min-w-0 flex-1 truncate text-[11px] font-medium leading-4 text-muted-foreground'")
    expect(src).not.toContain('className="flex items-center justify-between gap-2"')
  })

  it('keeps KG enabled in high-quality indexing while economical can disable it', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pipeline-options-panel.tsx'), 'utf8')

    const economicalBlock = src.slice(src.indexOf("economical: {"), src.indexOf("high_quality: {"))
    const highQualityBlock = src.slice(src.indexOf("high_quality: {"), src.indexOf("const PIPELINE_OPTION_LABELS"))

    expect(economicalBlock).toContain('kg_enabled: false,')
    expect(highQualityBlock).toContain('kg_enabled: true,')
    expect(highQualityBlock).toContain('event_vector_enabled: true,')
    expect(highQualityBlock).toContain('entity_vector_enabled: true,')
  })
})
