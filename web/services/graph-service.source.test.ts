import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph service source', () => {
  it('uses structuredClone instead of JSON stringify/parse deep copies', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-service.ts'), 'utf8')

    expect(src).toContain('structuredClone(')
    expect(src).not.toContain('JSON.parse(JSON.stringify')
  })
})
