import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('PageHeader source', () => {
  it('uses sidebar-tinted icon chrome and stronger typography hierarchy', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-header.tsx'), 'utf8')

    expect(src).toContain('bg-sidebar/80')
    expect(src).toContain('backdrop-blur-xl')
    expect(src).toContain('text-4xl md:text-5xl')
    expect(src).toContain('tracking-[-0.03em]')
    expect(src).toContain('leading-[1.75]')
  })
})
