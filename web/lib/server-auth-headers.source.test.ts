import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('server auth headers source', () => {
  it('builds backend auth headers from the current request context and oidc refresh bridge', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'server-auth-headers.ts'), 'utf8')

    expect(src).toContain("import 'server-only'")
    expect(src).toContain("import { cookies, headers } from 'next/headers'")
    expect(src).toContain('/api/oidc/refresh')
    expect(src).toContain("'Authorization'")
    expect(src).toContain("'Accept-Language'")
    expect(src).toContain("'X-User-ID'")
    expect(src).toContain("'X-Tenant-ID'")
    expect(src).toContain('export async function getServerAuthHeaders()')
  })
})
