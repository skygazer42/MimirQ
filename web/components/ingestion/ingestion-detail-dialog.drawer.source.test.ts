import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion detail dialog drawer', () => {
  it('renders ingestion details as a right-side drawer instead of a centered modal', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'ingestion-detail-dialog.tsx'), 'utf8')

    expect(src).toContain('<Sheet open={open} onOpenChange={onOpenChange}>')
    expect(src).toContain('side="right"')
    expect(src).toContain('h-[100dvh]')
    expect(src).toContain('w-[min(820px,100vw)] max-w-[820px] overflow-hidden border-l border-border/60 bg-background/95 shadow-strong')
    expect(src).toContain('<SheetHeader className="sr-only">')
    expect(src).not.toContain('max-w-3xl p-0 overflow-hidden sm:rounded-2xl')
  })
})
