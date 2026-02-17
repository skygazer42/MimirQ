import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('PageScaffold toolbar', () => {
  it('wraps toolbars with the shared PageToolbar primitive', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-scaffold.tsx'), 'utf8')
    expect(src).toContain('PageToolbar')
  })
})
