import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('navbar active route indicator', () => {
  it('adds a stable primary rail indicator for active items', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')
    expect(src).toContain('before:bg-gradient-to-b before:from-sky-500 before:to-blue-600')
  })
})
