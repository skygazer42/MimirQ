import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('document-detail-dialog visual contract', () => {
  it('keeps document detail on a single ruled surface with foreground boundaries', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'document-detail-dialog.tsx'),
      'utf8'
    )

    expect(src).toContain('DialogContent className="!max-w-5xl h-[80vh] overflow-hidden rounded-lg border border-foreground/10 bg-background !p-0 !gap-0"')
    expect(src).toContain('header className="flex items-start justify-between gap-6 border-b border-foreground/15 bg-background px-6 py-4"')
    expect(src).toContain('footer className="border-t border-foreground/15 bg-background px-6 py-4"')
    expect(src).toContain('rounded-xl border border-foreground/10 bg-background/70 text-primary')
    expect(src).toContain('rounded-full border border-foreground/10 bg-background/70')
    expect(src).not.toContain('rounded-2xl border border-border bg-primary/10')
    expect(src).not.toContain('border-b border-border bg-muted/20')
    expect(src).not.toContain('border-t border-border bg-muted/20')
  })
})
