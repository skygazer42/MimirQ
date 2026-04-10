import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('parse compare dialog source', () => {
  it('includes element-aware structure diff summaries above the raw markdown patch', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parse-compare-dialog.tsx'), 'utf8')

    expect(src).toContain("from '@/lib/parsing-element-diff'")
    expect(src).toContain('const elementDiffSummary = useMemo(')
    expect(src).toContain('结构差异')
    expect(src).toContain('新增')
    expect(src).toContain('移除')
  })
})
