import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('evaluations page query convergence', () => {
  it('uses TanStack Query for conversations, runs, and run detail loading', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { useQuery } from '@tanstack/react-query'")
    expect(src).toContain('queryKey: queryKeys.chat.conversations({ limit: 100 })')
    expect(src).toContain('queryKey: queryKeys.evaluations.ragasRuns({ limit: 50 })')
    expect(src).toContain('queryKey: queryKeys.evaluations.ragasRunDetail(selectedRunId, {')
    expect(src).toContain('refetchInterval: (query) => {')
    expect(src).not.toContain('const loadConversations = useCallback(async () => {')
    expect(src).not.toContain('const loadRuns = useCallback(async (conversationId?: string) => {')
    expect(src).not.toContain('Promise.all([loadConversations(), loadRuns()])')
    expect(src).toContain('await Promise.all([conversationsQuery.refetch(), runsQuery.refetch()])')
    expect(src).toContain('await runsQuery.refetch()')
  })
})
