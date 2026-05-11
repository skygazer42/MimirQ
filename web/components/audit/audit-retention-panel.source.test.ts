import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { readMessageCatalogSource } from '@/lib/source-test-utils'

describe('AuditRetentionPanel source', () => {
  it('exposes audit log export and purge as explicit business actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'audit-retention-panel.tsx'), 'utf8')
    const messages = readMessageCatalogSource(path.resolve(__dirname, '../..'))

    expect(src).toContain('auditApi.exportLogs')
    expect(src).toContain('auditApi.purgeLogs')
    expect(src).toContain("t('export')")
    expect(src).toContain("t('purge')")
    expect(messages).toContain("export: '导出审计日志'")
    expect(messages).toContain("purge: '清理审计日志'")
  })
})
