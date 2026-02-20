import { describe, expect, it } from 'vitest'

import { parseKnowledgeQueryState, serializeKnowledgeQueryState } from './use-knowledge-query-state'

describe('Knowledge query state helpers', () => {
  it('parses defaults when query is empty', () => {
    const state = parseKnowledgeQueryState(new URLSearchParams())

    expect(state).toEqual({
      activeTab: 'documents',
      viewMode: 'list',
      docFilter: '',
      statusFilter: 'all',
      lifecycleFilter: 'active',
      datasetScope: '__all__',
      folderPath: null,
      sortKey: 'created_at',
      sortDir: 'desc',
      connectorRunId: null,
    })
  })

  it('parses a full query string into state', () => {
    const state = parseKnowledgeQueryState(
      new URLSearchParams(
        'tab=retrieval&view=list&q=hello%20world&status=processing&lifecycle=archived&dataset=ds1&folder=/team&order_by=filename&order_dir=asc'
      )
    )

    expect(state).toEqual({
      activeTab: 'retrieval',
      viewMode: 'list',
      docFilter: 'hello world',
      statusFilter: 'processing',
      lifecycleFilter: 'archived',
      datasetScope: 'ds1',
      folderPath: '/team',
      sortKey: 'filename',
      sortDir: 'asc',
      connectorRunId: null,
    })
  })

  it('ignores folder when dataset is not selected', () => {
    const state = parseKnowledgeQueryState(new URLSearchParams('folder=/should_be_ignored'))

    expect(state.folderPath).toBeNull()
  })

  it('serializes state into a stable query string and omits defaults', () => {
    const qs = serializeKnowledgeQueryState({
      activeTab: 'retrieval',
      viewMode: 'list',
      docFilter: 'hello world',
      statusFilter: 'processing',
      lifecycleFilter: 'archived',
      datasetScope: 'ds1',
      folderPath: '/team',
      sortKey: 'filename',
      sortDir: 'asc',
      connectorRunId: null,
    })

    expect(qs).toBe(
      'tab=retrieval&q=hello+world&status=processing&lifecycle=archived&dataset=ds1&folder=%2Fteam&order_by=filename&order_dir=asc'
    )

    expect(
      serializeKnowledgeQueryState({
        activeTab: 'documents',
        viewMode: 'list',
        docFilter: '',
        statusFilter: 'all',
        lifecycleFilter: 'active',
        datasetScope: '__all__',
        folderPath: null,
        sortKey: 'created_at',
        sortDir: 'desc',
        connectorRunId: null,
      })
    ).toBe('')
  })

  it('supports deep links to a connector run in settings', () => {
    const state = parseKnowledgeQueryState(new URLSearchParams('run=run_123'))

    expect(state.activeTab).toBe('settings')
    expect(state.connectorRunId).toBe('run_123')

    expect(
      serializeKnowledgeQueryState({
        activeTab: 'settings',
        viewMode: 'list',
        docFilter: '',
        statusFilter: 'all',
        lifecycleFilter: 'active',
        datasetScope: '__all__',
        folderPath: null,
        sortKey: 'created_at',
        sortDir: 'desc',
        connectorRunId: 'run_123',
      })
    ).toBe('tab=settings&run=run_123')
  })
})
