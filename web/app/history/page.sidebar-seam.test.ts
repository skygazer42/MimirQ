import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history page sidebar seams', () => {
  it('uses a visibly denser sidebar layout with shallower horizontal padding across the whole history lane', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('className="sticky top-0 z-20 border-b border-border/50 px-2 pt-2 pb-1.5 space-y-1 min-w-[19.5rem] backdrop-blur-md bg-background/80"')
    expect(src).toContain('className="flex-1 overflow-y-auto overscroll-contain no-scrollbar px-0 py-0.5"')
    expect(src).toContain('className="relative group px-0"')
    expect(src).toContain('className="sticky top-0 z-10 px-0 pb-0 pt-0 bg-transparent"')
    expect(src).toContain('className="space-y-0 px-0 pb-0"')
    expect(src).toContain("'w-full flex flex-col gap-0.5 px-3 py-1.5 text-left transition-all duration-200 rounded-xl relative overflow-hidden border border-transparent focus-visible:outline-none focus-visible:ring-0'")
    expect(src).not.toContain('border-b border-border/50 px-3 pt-2 pb-1.5 space-y-1 min-w-[19.5rem]')
    expect(src).not.toContain('relative group px-2')
    expect(src).not.toContain('sticky top-0 z-10 px-0 pb-0.5 pt-0 bg-transparent')
    expect(src).not.toContain("'w-full flex flex-col gap-0.5 px-4 py-1.5 text-left transition-all duration-200 rounded-xl relative overflow-hidden border border-transparent focus-visible:outline-none focus-visible:ring-0'")
  })
})
