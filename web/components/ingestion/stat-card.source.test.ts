import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion stat card source', () => {
  it('renders either a real sparkline or an explicit placeholder variant', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'stat-card.tsx'), 'utf8')

    expect(src).toContain('<svg viewBox="0 0 80 24"')
    expect(src).toContain('aria-hidden="true"')
    expect(src).toContain("sparklineMode === 'placeholder' ? '4 3' : undefined")
    expect(src).toContain('buildSparklinePath')
    expect(src).toContain("sparklineMode === 'placeholder'")
  })
})
