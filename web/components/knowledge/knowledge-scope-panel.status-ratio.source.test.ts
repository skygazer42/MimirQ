import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('KnowledgeScopePanel status ratios', () => {
  it('adds a thin in-button ratio bar so status distribution is visible at a glance', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-scope-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'ratioClassName')
    expectSourceToContain(
      src,
      "showRatioBar: item.key !== 'all' && count > 0 && Number(totalDocs || 0) > 0"
    )
    expectSourceToContain(
      src,
      "className={cn('pointer-events-none absolute inset-x-2 bottom-1 h-[2px] rounded-full opacity-90', item.ratioClassName)}"
    )
    expectSourceToContain(src, "item.key === 'failed'")
    expectSourceToContain(src, "item.key === 'quarantined'")
    expectSourceToContain(
      src,
      "min-h-7 rounded-[10px] border px-2 py-1 text-[11px] font-semibold"
    )
    expectSourceToContain(src, 'text-foreground/76')
    expectSourceNotToContain(src, "count === 0\n              ? 'opacity-20")
  })
})
