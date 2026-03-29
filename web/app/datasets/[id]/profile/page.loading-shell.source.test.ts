import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset profile page loading shell', () => {
  it('uses a dataset-specific loading shell instead of a blank fallback div', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('PageLoading')
    expect(src).toContain('正在加载数据集画像...')
    expect(src).toContain('Loading dataset profile')
    expect(src).not.toContain('<div className="min-h-dvh bg-background" />')
  })
})
