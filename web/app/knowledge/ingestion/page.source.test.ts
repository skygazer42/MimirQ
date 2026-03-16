import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge ingestion page source', () => {
  it('wraps the description separator and trailing copy in explicit spans', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('<span className="text-muted-foreground/60">|</span>')
    expect(src).toContain('<span>实时追踪解析、切块、向量化与索引构建进度。</span>')
  })
})
