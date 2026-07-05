import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('KnowledgeScopePanel status ratios', () => {
  it('keeps status chips focused on label, count, and selected state without ratio bars', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-scope-panel.tsx'),
      'utf8'
    )

    expectSourceNotToContain(src, 'ratioClassName')
    expectSourceNotToContain(src, 'showRatioBar')
    expectSourceNotToContain(src, 'getDocStatusRatio')
    expectSourceNotToContain(src, 'bottom-1 h-[2px]')
    expectSourceNotToContain(src, 'Math.max(item.ratio')
    expectSourceToContain(
      src,
      "min-h-7 rounded-[10px] border px-2 py-1 text-[11px] font-semibold"
    )
    expectSourceToContain(src, 'text-foreground/76')
    expectSourceNotToContain(src, "count === 0\n              ? 'opacity-20")
  })
})
