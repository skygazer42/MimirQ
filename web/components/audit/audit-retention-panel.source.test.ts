import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('AuditRetentionPanel source', () => {
  it('exposes audit log export and purge as explicit business actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'audit-retention-panel.tsx'), 'utf8')

    expect(src).toContain('auditApi.exportLogs')
    expect(src).toContain('auditApi.purgeLogs')
    expect(src).toContain('导出审计日志')
    expect(src).toContain('清理审计日志')
  })
})
