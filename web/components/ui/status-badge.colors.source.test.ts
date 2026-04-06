import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('StatusBadge status tones', () => {
  it('uses distinct semantic colors so completed stays green, processing turns light orange, and failed stays light red', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'status-badge.tsx'), 'utf8')

    expect(src).toContain('className: "bg-success/10 text-success border-success/25"')
    expect(src).toContain('className: "bg-warning/10 text-warning border-warning/20"')
    expect(src).toContain('className: "bg-destructive/10 text-destructive border-destructive/20"')
  })
})
