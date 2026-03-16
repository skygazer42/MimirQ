import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('global error page source', () => {
  it('avoids exporting a function named Error', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'error.tsx'), 'utf8')

    expect(src).not.toContain('export default function Error(')
    expect(src).toContain('function GlobalErrorView(')
    expect(src).toContain('export default GlobalErrorView')
  })
})
