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

  it('surfaces manual sync success and captures queue refresh failures', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { captureApiError } from '@/lib/api-error-reporting'")
    expect(src).toContain('type QueueSyncStatus')
    expect(src).toContain('setLastQueueSync')
    expect(src).toContain("toast.success(message)")
    expect(src).toContain("toast.error(info.message)")
    expect(src).toContain("tags: { page: 'knowledge-quarantine', action: 'manual-sync' }")
    expect(src).toContain("同步完成：当前没有隔离或失败记录")
    expect(src).toContain("void refreshQueue({ notify: true })")
  })
})
