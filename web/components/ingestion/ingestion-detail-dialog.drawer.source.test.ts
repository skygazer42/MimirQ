import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion detail dialog drawer', () => {
  it('renders ingestion details as a right-side drawer instead of a centered modal', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'ingestion-detail-dialog.tsx'), 'utf8')

    expect(src).toContain('<Dialog open={open} onOpenChange={onOpenChange}>')
    expect(src).toContain('left-auto right-0 top-0 h-dvh w-[min(560px,100vw)] max-w-[560px] translate-x-0 translate-y-0 rounded-none p-0 overflow-hidden')
    expect(src).toContain('<DialogHeader className="sr-only">')
    expect(src).not.toContain('max-w-3xl p-0 overflow-hidden sm:rounded-2xl')
  })
})
