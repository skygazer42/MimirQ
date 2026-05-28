import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('model provider card typography', () => {
  it('sets a compact root font so unstyled children do not inherit browser defaults', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'model-provider-card.tsx'), 'utf8')

    expect(src).toContain('text-left text-[12px] leading-4 text-foreground/78')
    expect(src).toContain('truncate text-[13px] font-semibold leading-5 text-foreground')
    expect(src).toContain('line-clamp-2 text-[11px] font-medium leading-4 text-muted-foreground')
  })
})
