// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain, expectSourceToContain } from '@/lib/source-test-utils'

describe('usage page visual boundary contract', () => {
  it('keeps the usage overview on the flat boundary baseline', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src,
      "const USAGE_PANEL_CLASS = 'overflow-hidden rounded-xl border border-foreground/10 bg-background shadow-none'"
    )
    expectSourceToContain(src,
      "const USAGE_SURFACE_CLASS = 'rounded-xl border border-foreground/10 bg-background/80'"
    )
    expectSourceNotToContain(src, 'Ambient background glow')
    expectSourceNotToContain(src, 'blur-[120px]')
    expectSourceNotToContain(src, 'blur-[100px]')
    expectSourceNotToContain(src, 'backdrop-blur-xl')
    expectSourceNotToContain(src, 'rounded-2xl border border-primary/20 bg-primary/10 text-primary shadow-inner')
  })
})
