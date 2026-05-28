import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('stale chunk recovery source', () => {
  it('recognizes Next chunk and dynamic import failures and reloads only once per route', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'stale-chunk-recovery.ts'),
      'utf8'
    )

    expect(src).toContain('ChunkLoadError')
    expect(src).toContain('Loading chunk [\\w-]+ failed')
    expect(src).toContain('failed to fetch dynamically imported module')
    expect(src).toContain('sessionStorage.getItem(storageKey)')
    expect(src).toContain('globalThis.window.location.reload()')
  })
})
