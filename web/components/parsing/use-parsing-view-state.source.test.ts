import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('parsing view state source', () => {
  it('uses React Query for parsing library sync and active content hydration', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-view-state.ts'), 'utf8')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toContain('const librarySyncQuery = useQuery(')
    expect(src).toContain("queryKey: ['parsing', 'library-documents']")
    expect(src).toContain('const activeLibraryContentQuery = useQuery(')
    expect(src).toContain("queryKey: ['parsing', 'library-content', activeLibraryFileId]")
    expect(src).toContain('enabled: Boolean(activeLibraryFileId')
    expect(src).toContain('enabled: isLibraryLoaded')
  })

  it('keeps parsing library sync requests within the backend listDocuments limit', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsing-view-state.ts'), 'utf8')

    expect(src).toContain('parsingApi.listDocuments({ skip: 0, limit: 200 })')
    expect(src).not.toContain('parsingApi.listDocuments({ skip: 0, limit: 500 })')
  })
})
