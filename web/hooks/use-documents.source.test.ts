import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('use-documents source', () => {
  it('uses TanStack Query for document list reads and mutations', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-documents.ts'), 'utf8')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.documents.list')
    expect(src).toContain('useMutation({')
  })
})
