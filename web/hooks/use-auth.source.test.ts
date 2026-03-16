import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('use-auth source', () => {
  it('uses a direct best-effort logout request without wrapping fetch.catch in a try block', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-auth.ts'), 'utf8')

    expect(src).not.toMatch(/const logout[\s\S]*try\s*\{\s*fetch\('\/api\/oidc\/logout'/)
    expect(src).toContain("void fetch('/api/oidc/logout'")
  })
})
