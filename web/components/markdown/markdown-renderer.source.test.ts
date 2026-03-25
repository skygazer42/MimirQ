import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('markdown renderer source', () => {
  it('routes protected backend images through the auth image component instead of query tokens', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'markdown-renderer.tsx'), 'utf8')

    expect(src).toContain('AuthImage')
    expect(src).not.toContain('maybeAttachImageAuthToken')
    expect(src).not.toContain("searchParams.set('token'")
    expect(src).not.toContain("searchParams.set('access_token'")
  })
})
