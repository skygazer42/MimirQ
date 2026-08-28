// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain, expectSourceToContain } from '@/lib/source-test-utils'

describe('audit page visual boundary contract', () => {
  it('removes blur and floating card treatment from the audit workspace', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src,
      "const AUDIT_PANEL_CLASS = `rounded-xl ${AUDIT_SURFACE_CLASS} shadow-none`"
    )
    expectSourceToContain(src,
      "const AUDIT_SURFACE_CLASS = 'border border-info/20 bg-background/72 text-foreground'"
    )
    expectSourceToContain(src,
      "const AUDIT_TABLE_HEAD_CLASS = 'border-b border-border/60 bg-info/[0.035] text-left'"
    )
    expectSourceToContain(src, 'bodyClassName="bg-info/[0.035] !pb-3"')
    expectSourceToContain(src, "accent: 'bg-info'")
    expectSourceToContain(src, "purple: 'border-info/25 bg-info/10 text-info'")
    expectSourceNotToContain(src, 'bg-card/82')
    expectSourceNotToContain(src, 'bg-card p-4 shadow-inner')
    expectSourceNotToContain(src, 'backdrop-blur')
    expectSourceNotToContain(src, 'shadow-[0_10px_28px_hsl(var(--primary)/0.045)]')
    expectSourceNotToContain(src, 'rounded-[1.15rem]')
  })
})
