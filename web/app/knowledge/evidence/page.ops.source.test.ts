import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge evidence operations', () => {
  it('mounts the evidence administration operations panel', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { EvidenceOpsPanel } from '@/components/evidence/evidence-ops-panel'")
    expect(src).toContain('<EvidenceOpsPanel')
  })
})
