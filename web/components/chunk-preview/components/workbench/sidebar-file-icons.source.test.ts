import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Chunk preview sidebar file metadata', () => {
  it('surfaces compact file-type metadata badges in the queue rows', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'sidebar-client.tsx'), 'utf8')

    expect(src).toContain('const fileTypeLabel = f.originalFileType ? String(f.originalFileType).toUpperCase() : null')
    expect(src).toContain('const fileMetaLabel = [')
    expect(src).toContain('rounded-md border border-border/45 bg-background/70 px-1 py-px font-medium text-muted-foreground/85')
    expect(src).toContain('<Check className="h-3 w-3 shrink-0 text-success" />')
    expect(src).toContain('<AlertCircle className="h-3 w-3 shrink-0 text-destructive" />')
  })
})
