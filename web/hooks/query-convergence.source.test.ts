import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('query convergence source', () => {
  it('uses query keys and useQuery for pipeline capabilities', () => {
    const src = read('../contexts/pipeline-capabilities-context.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.pipeline.capabilities')
    expect(src).toContain("import { normalizeParserBackendName } from '@/lib/parser-compat'")
    expect(src).not.toContain('function normalizeParserBackendName')
  })

  it('uses useQuery for auth profile loading', () => {
    const src = read('./use-auth.ts')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.auth.profile')
  })

  it('uses useQuery for connector runs loading', () => {
    const src = read('./use-connector-runs.ts')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.connectors.runs')
  })

  it('uses useQuery for index audit results', () => {
    const src = read('./use-index-audit.ts')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.indexAudit.result')
  })

  it('uses QueryClient-backed loading for chat session messages', () => {
    const src = read('./use-chat-session.ts')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toContain('useQueryClient(')
    expect(src).toContain('queryKeys.chat.messages')
    expect(src).toContain('queryClient.fetchQuery')
  })
})
