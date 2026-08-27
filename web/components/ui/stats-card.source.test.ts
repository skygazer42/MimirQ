// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'
import { expectSourceNotToContain, expectSourceToContain } from '@/lib/source-test-utils'

describe('stats card visual boundary contract', () => {
  it('keeps stat cards structural instead of gradient glass tiles', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'stats-card.tsx'), 'utf8')

    expectSourceToContain(src,
      "const silentColorStyle = 'border-foreground/10 bg-muted/18 text-muted-foreground'"
    )
    expectSourceToContain(src,
      "'group relative overflow-hidden transition-all duration-200', 'flex items-center gap-4 rounded-xl border border-foreground/10 bg-background px-5 py-4 shadow-none hover:border-primary/18'"
    )
    expectSourceNotToContain(src, 'linear-gradient')
    expectSourceNotToContain(src, 'backdrop-blur-sm')
    expectSourceNotToContain(src, 'hover:scale-[1.02]')
  })
})
