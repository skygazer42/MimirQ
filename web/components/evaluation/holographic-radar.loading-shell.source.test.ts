import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('holographic radar loading shell', () => {
  it('renders the PageLoading shell instead of a plain pulse', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'holographic-radar.tsx'), 'utf8')

    expect(src).toContain('PageLoading')
    expect(src).toContain('正在加载评测雷达')
    expect(src).toContain('Loading holographic radar')
    expect(src).not.toContain('animate-pulse')
  })
})
