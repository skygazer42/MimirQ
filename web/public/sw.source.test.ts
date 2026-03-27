import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('service worker source', () => {
  it('pre-caches core app-shell routes and falls back to cached shell for offline navigation', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'sw.js'), 'utf8')

    expect(src).toContain("'/knowledge'")
    expect(src).toContain("'/knowledge/similarity'")
    expect(src).toContain("'/graph'")
    expect(src).toContain("url.pathname.startsWith('/lottie/')")
    expect(src).toContain("url.pathname.endsWith('.json')")
    expect(src).toContain("cache.match(request)")
    expect(src).toContain("cache.match('/')")
  })
})
