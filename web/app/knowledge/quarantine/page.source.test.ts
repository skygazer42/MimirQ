import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('quarantine queue page source', () => {
  it('uses helper components for dashboard stats and empty states instead of brittle inline markup', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).not.toContain('type DropReason = string')
    expect(src).toContain('.sort((a, b) => a.localeCompare(b))')
    expect(src).not.toContain('...(extra || {})')
    expect(src).toContain('if (extra) Object.assign(patch, extra)')
    expect(src).toContain('function SummaryStatCard(')
    expect(src).toContain('function QuarantineEmptyState(')
    expect(src).toContain('function QuarantineDetailPanel(')
  })
})
