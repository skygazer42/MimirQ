// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('evaluations page query convergence', () => {
  it('uses TanStack Query for conversations, runs, and run detail loading', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { useQuery } from '@tanstack/react-query'")
    expect(src).toContain("useState<ConversationEvidenceFilter>('ready')")
    expect(src).toContain('queryKey: queryKeys.chat.conversations({ limit: 100 })')
    expect(src).toContain('queryKeys.evaluations.ragasConversationReadiness(')
    expect(src).toContain('evaluationApi.getRagasConversationReadiness({')
    expect(src).toContain('queryKey: queryKeys.chat.messages(scopedConversationId)')
    expect(src).toContain('queryFn: () => chatApi.getMessages(scopedConversationId, { limit: 200 })')
    expect(src).toContain('setConversationEvidenceFilter(filter.id)')
    expect(src).toContain('filteredConversations.map((conversation) =>')
    expect(src).toContain('queryKey: queryKeys.evaluations.ragasRuns(runListParams)')
    expect(src).toContain('queryFn: () => evaluationApi.listRagasRuns(runListParams)')
    expect(src).toContain('const scopedConversationId = selectedConversationId || deepLinkedConversationId')
    expect(src).toContain('conversation_id: scopedConversationId')
    expect(src).toContain('summarizeConversationEvidence(messagesQuery.data?.messages || [])')
    expect(src).toContain('isMissingEvidence ||')
    expect(src).toContain("isMissingEvidence ? '缺证据，不能评测' : '开始评测'")
    expect(src).toContain('queryKey: queryKeys.evaluations.ragasRunDetail(selectedRunId, {')
    expect(src).toContain('refetchInterval: (query) => {')
    expect(src).toContain('runs.some((run) => run.id === prev)')
    expect(src).not.toContain('const loadConversations = useCallback(async () => {')
    expect(src).not.toContain('const loadRuns = useCallback(async (conversationId?: string) => {')
    expect(src).not.toContain('Promise.all([loadConversations(), loadRuns()])')
    expect(src).toContain('await Promise.all([conversationsQuery.refetch(), runsQuery.refetch()])')
    expect(src).toContain('await runsQuery.refetch()')
  })
})
