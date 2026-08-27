// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain, expectSourceToContain } from '@/lib/source-test-utils'

describe('tenant quota panel visual boundary contract', () => {
  it('keeps quota panels flat and structural', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'tenant-quota-panel.tsx'), 'utf8')

    expectSourceToContain(src,
      "const TENANT_QUOTA_PANEL_CLASS = 'overflow-hidden rounded-xl border border-foreground/10 bg-background shadow-none'"
    )
    expectSourceToContain(src,
      "const QUOTA_CARD_CLASS = 'rounded-lg border border-foreground/10 bg-background/80 px-3 py-2.5 shadow-none transition-colors hover:border-primary/18 hover:bg-muted/18'"
    )
    expectSourceNotToContain(src, 'shadow-[0_10px_28px_hsl(var(--primary)/0.045)]')
    expectSourceNotToContain(src, 'rounded-[1.15rem]')
  })
})
