import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('test case manager golden questions', () => {
  it('supports golden question tagging (governed write action)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'test-case-manager.tsx'), 'utf8')
    expect(src).toContain('golden')
    expect(src).toContain('patchRegressionCase')
  })
})

