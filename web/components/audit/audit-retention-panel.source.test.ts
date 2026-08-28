// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain, expectSourceToContain } from '@/lib/source-test-utils'

describe('audit retention panel visual boundary contract', () => {
  it('uses a ruled header without decorative gradients', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'audit-retention-panel.tsx'), 'utf8')

    expectSourceToContain(src,
      "const AUDIT_RETENTION_PANEL_CLASS = 'mt-3 overflow-hidden rounded-xl border border-info/20 bg-background/70 shadow-none'"
    )
    expectSourceToContain(src,
      "const AUDIT_RETENTION_HEADER_CLASS = 'flex flex-col gap-3 border-b border-border/60 bg-info/[0.025] px-4 py-3 lg:flex-row lg:items-center lg:justify-between'"
    )
    expectSourceToContain(src, 'border border-info/20 bg-info/10 text-info')
    expectSourceToContain(src,
      'xl:grid-cols-[minmax(0,1fr)_150px_150px_auto] xl:items-end'
    )
    expectSourceNotToContain(src,
      'lg:grid-cols-[minmax(0,1fr)_150px_150px_auto] lg:items-end'
    )
    expectSourceNotToContain(src, 'bg-[linear-gradient(90deg')
    expectSourceNotToContain(src, 'shadow-[0_10px_28px_hsl(var(--primary)/0.045)]')
  })
})
