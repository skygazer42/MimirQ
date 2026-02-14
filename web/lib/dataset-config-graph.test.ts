import { describe, expect, it } from 'vitest'

import { buildDatasetConfigGraph } from './dataset-config-graph'

describe('buildDatasetConfigGraph', () => {
  it('creates stable base nodes/links for empty bundle', () => {
    const g = buildDatasetConfigGraph({})
    const nodeIds = new Set(g.nodes.map((n) => n.id))

    expect(nodeIds.has('bundle')).toBe(true)
    expect(nodeIds.has('ingestion_defaults')).toBe(true)
    expect(nodeIds.has('pipeline')).toBe(true)
    expect(nodeIds.has('ingestion_policy')).toBe(true)
    expect(nodeIds.has('rag_defaults')).toBe(true)
    expect(nodeIds.has('prompt_defaults')).toBe(true)

    expect(g.links.some((l) => l.source === 'bundle' && l.target === 'pipeline')).toBe(true)
  })

  it('adds pipeline sub-block nodes when pipeline is configured', () => {
    const g = buildDatasetConfigGraph({
      pipeline: {
        governance_enabled: true,
        chunk_size: 600,
        bm25_index_enabled: true,
        table_store_enabled: true,
      },
    })
    const nodeIds = new Set(g.nodes.map((n) => n.id))
    expect(nodeIds.has('pipeline_governance')).toBe(true)
    expect(nodeIds.has('pipeline_chunking')).toBe(true)
    expect(nodeIds.has('pipeline_indexing')).toBe(true)
    expect(nodeIds.has('pipeline_tables')).toBe(true)
  })
})

