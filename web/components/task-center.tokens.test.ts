import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('task-center typography and token hooks', () => {
  it('uses semantic shell tokens and stronger label typography', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'task-center.tsx'), 'utf8')

    expect(src).toContain('bg-popover/90 text-popover-foreground')
    expect(src).toContain('ring-1 ring-primary/20')
    expect(src).toContain('ring-1 ring-destructive/20')
    expect(src).toContain('uppercase tracking-[0.12em] text-muted-foreground')
    expect(src).toContain('text-sm font-medium leading-snug tracking-tight truncate')
  })
})
