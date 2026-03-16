import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge feedback page source', () => {
  it('wraps the description separator and trailing copy in explicit spans', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('<span className="text-muted-foreground/50">|</span>')
    expect(src).toContain('<span>用户反馈实时监控与优化分析。</span>')
  })
})
