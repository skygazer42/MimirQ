import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('WorkbenchPanelDialog', () => {
  it('uses the shared Radix Dialog primitives and has an a11y label path for icon triggers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'workbench-panel-dialog.tsx'), 'utf8')

    expect(src).toContain('DialogContent')
    expect(src).toContain('DialogTrigger')

    // baseline-ui: icon-only buttons must have aria-labels.
    expect(src).toContain('label')
  })
})
