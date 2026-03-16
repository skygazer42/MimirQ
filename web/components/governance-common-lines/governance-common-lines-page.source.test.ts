import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('governance common lines source', () => {
  it('uses String.raw when building regex strings with backslashes', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-common-lines-page.tsx'), 'utf8')
    const rawMatches = src.match(/String\.raw`/g) ?? []

    expect(rawMatches.length).toBeGreaterThanOrEqual(3)
  })
})
