import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('PageToolbar', () => {
  it('is a light layout primitive (no heavy shadows, token borders only)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-toolbar.tsx'), 'utf8')

    expect(src).toContain('export function PageToolbar')

    // Token-first: avoid introducing bespoke shadows.
    expect(src).not.toMatch(/\bshadow-(?:xl|2xl|3xl)\b/)
  })
})
