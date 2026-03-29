import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset health loading shell', () => {
  it('renders the PageLoading message instead of the blank div', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('正在加载数据集健康状况...')
    expect(src).toContain('Loading dataset health overview')
    expect(src).toContain('PageLoading')
    expect(src).not.toContain('<div className="min-h-dvh bg-background" />')
  })
})
