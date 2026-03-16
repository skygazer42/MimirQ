import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('datasets page source', () => {
  it('avoids empty-object spreads and wraps adjacent description text explicitly', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'datasets-page.tsx'), 'utf8')

    expect(src).not.toContain('...(ds.pipeline || {})')
    expect(src).not.toContain('...(patch || {})')
    expect(src).toContain('<span>管理知识库集合与访问权限</span>')
  })
})
