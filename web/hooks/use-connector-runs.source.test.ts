import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('use-connector-runs source', () => {
  it('avoids any-based error catches', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-connector-runs.ts'), 'utf8')

    expect(src).not.toContain('catch (err: any)')
    expect(src).not.toContain(': any')
  })
})
