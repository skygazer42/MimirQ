import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('WorkbenchScaffold spacing', () => {
  it('uses mid-density defaults (px-6/md:px-8) and consistent section padding', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'workbench-scaffold.tsx'), 'utf8')
    expect(src).toContain('px-6 md:px-8')
    expect(src).toContain('pt-6 md:pt-8')
    expect(src).toContain('pb-5 md:pb-6')
    expect(src).toContain('pb-8')
  })
})

