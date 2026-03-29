import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge ingestion loading shell', () => {
  it('renders the branded PageLoading fallback message', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('正在加载知识库入库流程...')
    expect(src).toContain('Loading knowledge ingestion workspace')
    expect(src).toContain('PageLoading')
    expect(src).not.toContain('<div className="min-h-dvh bg-background" />')
  })
})
