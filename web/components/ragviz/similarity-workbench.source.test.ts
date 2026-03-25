import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('similarity workbench source', () => {
  it('avoids any-based helpers in the workbench and plot renderer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'similarity-workbench.tsx'), 'utf8')

    expect(src).not.toContain(': any')
    expect(src).not.toContain('as any')
    expect(src).not.toContain('Record<string, any>')
  })
})
