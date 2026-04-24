import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion error treemap source', () => {
  it('renders a clickable risk heatmap with selected-reason emphasis', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'error-treemap.tsx'), 'utf8')

    expect(src).toContain("import { cn } from '@/lib/utils'")
    expect(src).toContain('onReasonSelect')
    expect(src).toContain('selectedReason')
    expect(src).toContain('aria-label="风险重灾区热力图"')
    expect(src).toContain('role="grid"')
    expect(src).toContain('formatLabel')
    expect(src).toContain('timeLabel')
    expect(src).toContain('payload.name === selectedReason')
    expect(src).toContain('onClick={() => onReasonSelect(payload.name)}')
    expect(src).toContain('min-h-[74px]')
    expect(src).toContain('font-code tabular-nums')
    expect(src).toContain('text-[0.84rem] font-medium')
    expect(src).toContain('text-[0.68rem] uppercase')
  })
})
