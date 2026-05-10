import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion monitor utils source', () => {
  it('does not export sales-audit fallback artifacts for non-demo pages', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'monitor-utils.ts'), 'utf8')

    expect(src).not.toContain('SalesAuditFallbackArtifacts')
    expect(src).not.toContain('buildSalesAuditFallbackArtifacts')
    expect(src).not.toContain('fallback-documents')
  })
})
