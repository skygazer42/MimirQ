import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('GovernanceSection operations', () => {
  it('mounts stale document and chunk preset maintenance operations', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-section.tsx'), 'utf8')

    expect(src).toContain("import { GovernanceOpsPanel } from '@/components/settings/governance-ops-panel'")
    expect(src).toContain('<GovernanceOpsPanel')
  })
})
