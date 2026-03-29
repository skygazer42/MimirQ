import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('reports page loading shell', () => {
  it('uses the branded PageLoading fallback and not the blank div', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('PageLoading')
    expect(src).toContain('正在加载报告中心...')
    expect(src).toContain('Loading reports center')
    expect(src).not.toContain('<div className="min-h-dvh bg-background" />')
  })
})
