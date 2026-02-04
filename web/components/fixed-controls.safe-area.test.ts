import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('fixed controls safe-area', () => {
  it('navbar toggle respects safe-area-inset-bottom', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')
    expect(src).toContain('safe-area-inset-bottom')
  })

  it('task-center respects safe-area-inset-bottom', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'task-center.tsx'), 'utf8')
    expect(src).toContain('safe-area-inset-bottom')
  })
})

