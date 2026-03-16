import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('doc content cache source', () => {
  it('avoids async promise executors and rejects with Error instances', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'doc-content-cache.ts'), 'utf8')

    expect(src).not.toContain('new Promise(async')
    expect(src).toContain('function toError(')
    expect(src).not.toContain('reject(req.error)')
    expect(src).not.toContain('reject(tx.error)')
  })
})
