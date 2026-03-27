import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('document api service source', () => {
  it('keeps a real document service module instead of a passthrough re-export', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'api/documents.ts'), 'utf8')

    expect(src).not.toContain("export { documentApi } from '@/lib/api-client'")
    expect(src).toContain('export const documentApi = {')
    expect(src).toContain("from '@/lib/api/core'")
    expect(src).toContain('openapiRequest({')
  })

  it('keeps api-client as a compatibility barrel instead of owning documentApi directly', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'api-client.ts'), 'utf8')

    expect(src).not.toContain('export const documentApi = {')
    expect(src).toContain("export { documentApi } from '@/lib/api/documents'")
  })
})
