import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('DataGovernancePanel workbench layout', () => {
  it('adopts WorkbenchScaffold for the outer structure', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'data-governance-panel.tsx'), 'utf8')
    expect(src).toContain('WorkbenchScaffold')
  })
})

