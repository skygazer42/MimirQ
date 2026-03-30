import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dataset ingestion page source', () => {
  it('reuses the shared parser backend registry instead of maintaining a local duplicate list', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("from '@/lib/parser-options'")
    expect(src).toContain('PARSER_BACKEND_REGISTRY_OPTIONS')
    expect(src).toContain('PARSER_BACKEND_REGISTRY_OPTIONS.map((o) => (')
    expect(src).not.toContain('const PARSER_BACKEND_OPTIONS:')
  })

  it('reuses the shared chunk strategy fallback registry instead of keeping a local hardcoded list', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("from '@/lib/chunk-strategies'")
    expect(src).toContain('INGESTION_FALLBACK_CHUNK_STRATEGY_VALUES')
    expect(src).not.toContain("['langchain_recursive', 'integrated_naive', 'integrated_book', 'integrated_laws', 'integrated_email']")
  })
})
