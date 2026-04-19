import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history page group header surface', () => {
  it('keeps the sticky group header background transparent so only the pill carries color', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('sticky top-0 z-10 px-0 pb-0 pt-0 bg-transparent')
    expect(src).not.toContain('bg-card/95')
    expect(src).not.toContain('supports-[backdrop-filter]:bg-card/85')
  })
})
