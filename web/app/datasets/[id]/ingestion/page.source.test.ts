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

  it('loads governance profile options through TanStack Query instead of hand-written profile effects', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toContain('useQuery')
    expect(src).toContain('queryKey: queryKeys.governance.profiles')
    expect(src).not.toContain('const [profiles, setProfiles]')
    expect(src).not.toContain('const loadProfiles')
    expect(src).not.toContain('setProfiles(')
  })

  it('loads dataset, ingestion policy, and ingestion stats through TanStack Query', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('queryKey: queryKeys.datasets.detail')
    expect(src).toContain('queryKey: queryKeys.datasets.ingestionPolicy')
    expect(src).toContain('queryKey: queryKeys.datasets.ingestionStats')
    expect(src).toContain('refreshIngestionPolicy')
    expect(src).not.toContain('const [dataset, setDataset]')
    expect(src).not.toContain('const [ingestionStats, setIngestionStats]')
    expect(src).not.toContain('const [loading, setLoading]')
    expect(src).not.toContain('const load = useCallback')
    expect(src).not.toContain('await load()')
  })

  it('does not keep dead local ingestion policy version-history loaders around', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).not.toContain('const loadVersions = useCallback(async () => {')
    expect(src).not.toContain('await loadVersions()')
    expect(src).not.toContain('detachPromise(loadVersions())')
  })
})
