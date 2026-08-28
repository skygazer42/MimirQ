// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain, expectSourceToContain } from '@/lib/source-test-utils'

describe('tenant quota panel visual boundary contract', () => {
  it('keeps quota panels flat and structural', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'tenant-quota-panel.tsx'), 'utf8')

    expectSourceToContain(src,
      "const TENANT_QUOTA_PANEL_CLASS = 'overflow-hidden rounded-xl border border-info/20 bg-background/72 shadow-none'"
    )
    expectSourceToContain(src,
      "const QUOTA_CARD_CLASS = 'rounded-lg border border-border/70 bg-background/62 px-3 py-2.5 shadow-none transition-colors hover:border-info/25 hover:bg-info/[0.04]'"
    )
    expectSourceToContain(src, 'hover:border-info/30 hover:bg-info/[0.07] hover:text-info')
    expectSourceToContain(src, "exceeded ? 'text-destructive' : 'text-success'")
    expectSourceNotToContain(src, 'shadow-[0_10px_28px_hsl(var(--primary)/0.045)]')
    expectSourceNotToContain(src, 'rounded-[1.15rem]')
  })
})
