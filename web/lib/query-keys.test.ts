import { describe, expect, it } from 'vitest'

import { queryKeys } from './query-keys'

describe('queryKeys', () => {
  it('builds stable document and dataset keys', () => {
    expect(queryKeys.documents.all).toEqual(['documents'])
    expect(queryKeys.documents.list({ dataset_id: 'dataset-1', limit: 20 })).toEqual([
      'documents',
      'list',
      { dataset_id: 'dataset-1', limit: 20 },
    ])
    expect(queryKeys.datasets.detail('dataset-1')).toEqual(['datasets', 'detail', 'dataset-1'])
  })

  it('covers auth, dataset, pipeline, connector, index audit, and health namespaces', () => {
    expect(queryKeys.auth.profile).toEqual(['auth', 'profile'])
    expect(queryKeys.datasets.health('dataset-1')).toEqual(['datasets', 'health', 'dataset-1'])
    expect(queryKeys.pipeline.capabilities).toEqual(['pipeline', 'capabilities'])
    expect(queryKeys.connectors.runs({ datasetId: 'dataset-1', limit: 20 })).toEqual([
      'connectors',
      'runs',
      { datasetId: 'dataset-1', limit: 20 },
    ])
    expect(queryKeys.indexAudit.result('dataset-1')).toEqual(['indexAudit', 'dataset-1'])
    expect(queryKeys.health.meta).toEqual(['meta'])
  })
})
