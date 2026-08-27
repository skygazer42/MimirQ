// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain, expectSourceToContain } from '@/lib/source-test-utils'

describe('settings page visual boundary contract', () => {
  it('uses ruled section frames instead of gradient floating cards', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src,
      "const SETTINGS_CARD_CLASS = 'rounded-xl border border-foreground/10 bg-background shadow-none'"
    )
    expectSourceToContain(src,
      'data-testid="settings-metric-strip" className="flex flex-wrap items-center gap-1.5 rounded-xl border border-foreground/10 bg-background p-1.5"'
    )
    expectSourceToContain(src,
      "'relative scroll-mt-24 overflow-visible rounded-xl border border-foreground/10 bg-background shadow-none'"
    )
    expectSourceToContain(src,
      '<div className="border-b border-foreground/10 bg-muted/18 px-4 py-3">'
    )
    expectSourceNotToContain(src, 'bg-[linear-gradient(90deg')
    expectSourceNotToContain(src, 'before:absolute before:-left-3')
    expectSourceNotToContain(src, 'shadow-[0_14px_34px_hsl(var(--foreground)/0.035)]')
  })
})
