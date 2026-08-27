// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain, expectSourceToContain } from '@/lib/source-test-utils'

describe('audit retention panel visual boundary contract', () => {
  it('uses a ruled header without decorative gradients', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'audit-retention-panel.tsx'), 'utf8')

    expectSourceToContain(src,
      "const AUDIT_RETENTION_PANEL_CLASS = 'mt-3 overflow-hidden rounded-xl border border-foreground/10 bg-background shadow-none'"
    )
    expectSourceToContain(src,
      "const AUDIT_RETENTION_HEADER_CLASS = 'flex flex-col gap-3 border-b border-foreground/10 bg-muted/18 px-4 py-3 lg:flex-row lg:items-center lg:justify-between'"
    )
    expectSourceNotToContain(src, 'bg-[linear-gradient(90deg')
    expectSourceNotToContain(src, 'shadow-[0_10px_28px_hsl(var(--primary)/0.045)]')
  })
})
