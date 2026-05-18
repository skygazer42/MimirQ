import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('audit page productized operations', () => {
  it('mounts the audit export and retention operations panel', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { AuditRetentionPanel } from '@/components/audit/audit-retention-panel'")
    expect(src).toContain('<AuditRetentionPanel')
    expect(src).toContain('filters={auditOperationFilters}')
    expect(src).not.toContain('<AuditRetentionPanel />')
  })
})
