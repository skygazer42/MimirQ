// Source contract check only; behavior remains covered by the management smoke suite.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

const source = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

describe('groups Ocean theme surface', () => {
  it('uses flat Ocean surfaces without decorative metric progress', () => {
    expectSourceToContain(source,
      "const CARD_CLASS = 'rounded-xl border border-info/20 bg-background/72 shadow-none'"
    )
    expectSourceToContain(source,
      'bodyClassName="bg-info/[0.035] !pb-3 pt-1.5"'
    )
    expectSourceToContain(source,
      "primary: 'border-info/25 bg-info/10 text-info'"
    )
    expectSourceNotToContain(source, 'shadow-[0_14px_36px_hsl(var(--primary)/0.05)]')
    expectSourceNotToContain(source, 'shadow-[0_8px_20px_hsl(var(--info)/0.24)]')
    expectSourceNotToContain(source, 'bg-[linear-gradient(90deg')
    expectSourceNotToContain(source, "'h-full rounded-full transition-all'")
    expectSourceNotToContain(source, 'shadow-inner')
    expectSourceNotToContain(source, 'bg-card/88')
  })

  it('keeps list, toolbar and pagination in the Ocean surface family', () => {
    expectSourceToContain(source,
      'rounded-xl border border-info/15 bg-info/[0.025] p-3'
    )
    expectSourceToContain(source,
      'grid grid-cols-12 bg-info/[0.035] px-4 py-2.5'
    )
    expectSourceToContain(source, 'hover:bg-info/[0.04]')
    expectSourceToContain(source, 'bg-info px-3 py-1.5 text-[13px]')
  })
})
