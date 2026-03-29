import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('queryset health tab loading shell', () => {
  it('renders the branded panel skeleton rather than a bare pulse block', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'queryset-health-tab.tsx'), 'utf8')

    expect(src).toContain('className="h-80 rounded-2xl border border-border/60')
    expect(src).toContain('Panel className')
    expect(src).toContain('Skeleton className="h-4 w-full"')
    expect(src).not.toContain('animate-pulse')
  })
})
