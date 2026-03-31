import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('service worker source', () => {
  it('uses a conservative, versioned caching strategy for offline shell reliability', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'sw.js'), 'utf8')

    expect(src).toContain("const CACHE_VERSION = 'v4'")
    expect(src).toContain("'/knowledge'")
    expect(src).toContain("'/knowledge/similarity'")
    expect(src).toContain("'/graph'")
    expect(src).toContain("url.pathname.startsWith('/lottie/')")
    expect(src).toContain("url.pathname.startsWith('/monaco/')")
    expect(src).toContain("url.pathname.startsWith('/pdfjs-dist/')")
    expect(src).toContain("url.pathname.startsWith('/fonts/')")
    expect(src).toContain("url.pathname.endsWith('.svg')")
    expect(src).not.toContain("url.pathname.endsWith('.json')")
    expect(src).toContain("pdf\\.worker(?:\\.min)?\\.[^.]+\\.mjs")
    expect(src).toContain("cache.match(request)")
    expect(src).toContain("cache.match('/')")
  })
})
