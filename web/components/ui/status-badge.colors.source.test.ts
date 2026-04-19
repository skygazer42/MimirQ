import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('StatusBadge status tones', () => {
  it('uses dot indicators with semantic colors for status differentiation', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'status-badge.tsx'), 'utf8')

    expect(src).toContain('dotColor: "bg-success"')
    expect(src).toContain('dotColor: "bg-warning"')
    expect(src).toContain('dotColor: "bg-destructive"')
  })
})
