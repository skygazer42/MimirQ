import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('navbar active route indicator', () => {
  it('adds a stable primary rail indicator for active items', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')
    expect(src).toContain(
      'before:bg-[linear-gradient(180deg,hsl(var(--info)),hsl(var(--primary)))]'
    )
  })
})
