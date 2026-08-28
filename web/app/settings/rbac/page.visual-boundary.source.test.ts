// Source contract check only; behavior remains covered by the management smoke suite.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'
import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

const source = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

describe('RBAC Ocean theme surface', () => {
  it('uses ruled Ocean surfaces without floating cards or purple role accents', () => {
    expectSourceToContain(source,
      "const CARD_CLASS = 'rounded-xl border border-info/20 bg-background/72 shadow-none'"
    )
    expectSourceToContain(source, 'bodyClassName="bg-info/[0.035] !pb-3"')
    expectSourceToContain(source,
      "cn: 'border-info/25 bg-info/10 text-info'"
    )
    expectSourceToContain(source, "admin: 'bg-info'")
    expectSourceToContain(source, "purple: 'border-info/25 bg-info/10 text-info'")
    expectSourceNotToContain(source, 'shadow-[0_10px_28px_hsl(var(--primary)/0.045)]')
    expectSourceNotToContain(source, 'bg-card/86')
    expectSourceNotToContain(source, 'bg-accent/10 text-accent')
  })

  it('keeps the member filters stacked until a wide desktop', () => {
    expectSourceToContain(source,
      'xl:grid-cols-[minmax(260px,1.1fr)_220px_220px_auto] xl:items-end'
    )
    expect(source).not.toContain(
      'lg:grid-cols-[minmax(260px,1.1fr)_220px_220px_auto] lg:items-end'
    )
  })
})
