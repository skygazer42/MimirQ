import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('export-openapi script', () => {
  it('prefers Python interpreters that can actually import FastAPI before exporting the spec', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'export-openapi.mjs'), 'utf8')

    expect(src).toContain("import importlib.util as u; import sys; sys.exit(0 if u.find_spec('fastapi') else 1)")
    expect(src).toContain('const fastApiCheck = spawnSync(')
    expect(src).toContain('if (fastApiCheck.status === 0)')
  })
})
