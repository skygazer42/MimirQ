// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain, expectSourceToContain } from '@/lib/source-test-utils'

describe('audit page visual boundary contract', () => {
  it('removes blur and floating card treatment from the audit workspace', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src,
      "const AUDIT_PANEL_CLASS = `rounded-xl ${AUDIT_SURFACE_CLASS} bg-background shadow-none`"
    )
    expectSourceToContain(src, "const AUDIT_TABLE_HEAD_CLASS = 'border-b border-foreground/10 bg-muted/18 text-left'")
    expectSourceNotToContain(src, 'backdrop-blur')
    expectSourceNotToContain(src, 'shadow-[0_10px_28px_hsl(var(--primary)/0.045)]')
    expectSourceNotToContain(src, 'rounded-[1.15rem]')
  })
})
