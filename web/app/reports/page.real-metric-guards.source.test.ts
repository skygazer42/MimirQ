import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('reports real metric guards', () => {
  it('does not present unmeasured governance-audit counters as measured zeros', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('const governanceAuditHasSamples =')
    expect(src).toContain("const governanceAuditUnavailableSub = '当前报告无治理审计样本'")
    expect(src).toContain('const governanceAuditUrlValue = governanceAuditHasSamples')
    expect(src).toContain('String(governanceAudit?.urls_changed_total || 0)')
    expect(src).toContain('const governanceAuditImageValue = governanceAuditHasSamples')
    expect(src).toContain('String(governanceAudit?.images_removed_total || 0)')
    expect(src).toContain('value={governanceAuditUrlValue}')
    expect(src).toContain('value={governanceAuditImageValue}')
  })

  it('derives success documents from explicit completed statuses when status counts exist', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('const hasStatusCounts = Object.keys(statusCounts).length > 0')
    expect(src).toContain('const successDocs = hasStatusCounts')
    expect(src).toContain('? completedDocs')
    expect(src).toContain(': Math.max(0, totalDocs - failed - quarantined)')
  })
})
