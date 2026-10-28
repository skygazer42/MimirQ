import { describe, expect, it } from 'vitest'
import { parseKnowledgeQueryState, serializeKnowledgeQueryState } from './use-knowledge-query-state'

describe('knowledge navigation', () => {
  it('keeps task deep links after retiring the settings tab', () => {
    const state = parseKnowledgeQueryState(new URLSearchParams('tab=settings&dataset=team&run=run-1'))
    expect(state).toMatchObject({ activeTab: 'documents', datasetScope: 'team', connectorRunId: 'run-1', tasksOpen: true })
    expect(serializeKnowledgeQueryState(state)).toBe('dataset=team&run=run-1')
  })

  it('opens the task list without the retired configuration page', () => {
    const state = parseKnowledgeQueryState(new URLSearchParams('tasks=1&dataset=team'))
    expect(state).toMatchObject({ activeTab: 'documents', tasksOpen: true })
    expect(serializeKnowledgeQueryState(state)).toBe('dataset=team&tasks=1')
    expect(serializeKnowledgeQueryState({ ...state, tasksOpen: false })).toBe('dataset=team')
  })

  it('preserves retrieval scope and document filters through navigation', () => {
    const params = 'tab=retrieval&q=API&status=failed&dataset=team&folder=manual&order_by=filename&order_dir=asc'
    expect(serializeKnowledgeQueryState(parseKnowledgeQueryState(new URLSearchParams(params)))).toBe(params)
  })
})
