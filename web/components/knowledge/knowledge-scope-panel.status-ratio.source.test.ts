import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel status ratios', () => {
  it('adds a thin in-button ratio bar so status distribution is visible at a glance', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-scope-panel.tsx'), 'utf8')

    expect(src).toContain('ratioClassName')
    expect(src).toContain("showRatioBar: item.key !== 'all' && count > 0 && Number(totalDocs || 0) > 0")
    expect(src).toContain("className={cn('pointer-events-none absolute inset-x-2 bottom-1 h-[2px] rounded-full opacity-90', item.ratioClassName)}")
    expect(src).toContain("item.key === 'failed'")
    expect(src).toContain("item.key === 'quarantined'")
  })
})
