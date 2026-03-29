import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset precheck page loading shell', () => {
  it('renders branded loading copy and avoids blank placeholder', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'page.tsx'),
      'utf8'
    )

    expect(src).toContain('PageLoading')
    expect(src).toContain('正在加载预检洞察...')
    expect(src).toContain('Loading dataset precheck insights')
    expect(src).not.toContain('<div className="min-h-dvh bg-background" />')
  })
})
