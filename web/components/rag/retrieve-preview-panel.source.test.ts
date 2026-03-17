import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('retrieve preview panel source', () => {
  it('uses direct citation fields in table rows and String directly for matched terms', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieve-preview-panel.tsx'), 'utf8')

    expect(src).toContain('terms.filter(Boolean).slice(0, 24).map(String)')
    expect(src).toContain("const chunkId = String(hit.chunk_id || '')")
    expect(src).toContain("const clause = String(hit.policy_clause_number || '')")
    expect(src).toContain("const pathStr = String(hit.policy_path_str || '')")
    expect(src).toContain("role.startsWith('hierarchy_')")
    expect(src).toContain('family_hit')
    expect(src).toContain('expanded')
  })
})
