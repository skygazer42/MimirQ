import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('observability page loading shell', () => {
  it('uses a branded loading shell instead of a blank fallback div', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('PageLoading')
    expect(src).toContain('正在加载可观测面板...')
    expect(src).toContain('Loading observability dashboard')
    expect(src).not.toContain('<div className="min-h-dvh bg-background" />')
  })
})
