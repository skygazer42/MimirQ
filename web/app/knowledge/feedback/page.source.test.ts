import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('feedback page source', () => {
  it('renders feedback summary cards in the design-reference KPI style', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('function FeedbackSummaryCard(')
    expect(src).toContain('min-h-[112px]')
    expect(src).toContain('size-14')
    expect(src).toContain('text-[2rem] font-black')
    expect(src).toContain('较昨日')
    expect(src).not.toContain('buildSparklinePath')
    expect(src).not.toContain('series={card.series}')
  })
})
