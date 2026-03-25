import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('env source', () => {
  it('reuses trimTrailingSlashes from utils', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'env.ts'), 'utf8')

    expect(src).toContain("import { trimTrailingSlashes } from './utils'")
    expect(src).not.toContain('function trimTrailingSlashes(')
  })
})
