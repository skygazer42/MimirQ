import { describe, expect, it } from 'vitest'
import { parseEvidenceCitations } from './evidence-citations'
import { buildWhyMissedReport, parseReferenceDriftDetails } from './evidence-why-missed'

describe('evidence reference diagnosis', () => {
  it('keeps reference metadata and independent source positions when duplicate pointers are diagnosed', () => {
    const references = [
      { document_id: 'doc', chunk_id: 'chunk', chunk_index: null, label: null },
      { document_id: 'doc', chunk_id: 'chunk', chunk_index: 0, label: '' },
    ]
    const report = buildWhyMissedReport({
      reference_sources: references,
      citations: parseEvidenceCitations([{ document_id: 'doc', chunk_id: 'chunk', retrieval_score: 0 }]),
      drifted_references: [],
      drift_complete: true,
    })
    expect(report.summary.retrieved_references).toBe(2)
    expect(report.references).toEqual([
      expect.objectContaining({
        sourceIndex: 0,
        chunk_index: null,
        label: null,
        retrieval: expect.objectContaining({ rank: 1, score: 0 }),
      }),
      expect.objectContaining({
        sourceIndex: 1,
        chunk_index: 0,
        label: '',
        retrieval: expect.objectContaining({ rank: 1, score: 0 }),
      }),
    ])
    expect(references[0].chunk_index).toBeNull()
  })

  it('does not turn a different raw pointer into a hit by trimming its identity', () => {
    const report = buildWhyMissedReport({
      reference_sources: [{ document_id: 'doc', chunk_id: 'chunk' }],
      citations: parseEvidenceCitations([{ document_id: ' doc ', chunk_id: ' chunk ' }]),
      drifted_references: [],
      drift_complete: true,
    })
    expect(report.references[0].status).toBe('missing')
    expect(report.references[0].retrieval).toBeUndefined()
    expect(report.references[0].hints).toBeUndefined()
  })

  it('keeps known drift and actual retrieval details when audit coverage is incomplete', () => {
    const report = buildWhyMissedReport({
      reference_sources: [
        { document_id: 'doc', chunk_id: 'known' },
        { document_id: 'doc', chunk_id: 'unconfirmed' },
      ],
      citations: parseEvidenceCitations([{ chunk_id: 'unconfirmed', retrieval_score: 0, hit_type: '' }]),
      drifted_references: [
        {
          suite_id: 'suite',
          item_id: 'item',
          item_status: 'draft',
          dataset_id: 'dataset',
          document_id: 'doc',
          chunk_id: 'known',
          reason: 'chunk_missing',
          expected: {
            document_id: 'doc',
            chunk_id: 'known',
            chunk_index: null,
            pipeline_hash: null,
            doc_pipeline_key: null,
            flag: false,
          },
          observed: {},
        },
      ],
      drift_complete: false,
    })
    expect(report.summary).toMatchObject({ drifted_references: 1, unknown_references: 1, retrieved_references: 0 })
    expect(report.references[0]).toMatchObject({
      status: 'drifted',
      drift: { reason: 'chunk_missing', expected: { flag: false } },
    })
    expect(report.references[1]).toMatchObject({ status: 'unknown', retrieval: { rank: 1, score: 0, hit_type: '' } })
  })
  it.each([
    { chunk_index: 1, pipeline_hash: 'current', doc_pipeline_key: 'current-key', reason: 'chunk_index_mismatch' },
    { chunk_index: 0, pipeline_hash: 'old', doc_pipeline_key: 'current-key', reason: 'pipeline_hash_mismatch' },
    { chunk_index: 0, pipeline_hash: 'current', doc_pipeline_key: 'old-key', reason: 'doc_pipeline_key_mismatch' },
  ])('does not give another saved reference the drift of the same chunk (%j)', (stale) => {
    const current = {
      document_id: 'doc',
      chunk_id: 'chunk',
      chunk_index: 0,
      pipeline_hash: 'current',
      doc_pipeline_key: 'current-key',
    }
    const staleReference = {
      ...current,
      chunk_index: stale.chunk_index,
      pipeline_hash: stale.pipeline_hash,
      doc_pipeline_key: stale.doc_pipeline_key,
    }
    const report = buildWhyMissedReport({
      reference_sources: [current, staleReference],
      citations: parseEvidenceCitations([{ document_id: 'doc', chunk_id: 'chunk', retrieval_score: 0 }]),
      drifted_references: [
        {
          suite_id: 'suite',
          item_id: 'item',
          item_status: 'draft',
          dataset_id: 'dataset',
          document_id: 'doc',
          chunk_id: 'chunk',
          reason: stale.reason,
          expected: staleReference,
          observed: {},
        },
      ],
      drift_complete: true,
    })
    expect(report.summary).toMatchObject({ drifted_references: 1, retrieved_references: 1 })
    expect(report.references.find((row) => row.sourceIndex === 0)?.status).toBe('retrieved')
    expect(report.references.find((row) => row.sourceIndex === 1)?.drift?.reason).toBe(stale.reason)
  })
  it('matches producer nulls to omitted fields without collapsing zero or empty metadata', () => {
    const detail = {
      item_id: 'item',
      document_id: 'doc',
      chunk_id: 'chunk',
      reason: 'chunk_missing',
      expected: {
        document_id: 'doc',
        chunk_id: 'chunk',
        chunk_index: null,
        pipeline_hash: null,
        doc_pipeline_key: null,
      },
      observed: {},
    }
    const report = buildWhyMissedReport({
      reference_sources: [
        { document_id: 'doc', chunk_id: 'chunk' },
        { document_id: 'doc', chunk_id: 'chunk', chunk_index: 0, pipeline_hash: '', doc_pipeline_key: '' },
      ],
      citations: [],
      drifted_references: parseReferenceDriftDetails([detail]),
      drift_complete: false,
    })
    expect(report.references.find((row) => row.sourceIndex === 0)?.status).toBe('drifted')
    expect(report.references.find((row) => row.sourceIndex === 1)?.status).toBe('unknown')
  })
  it('rejects a drift detail with no reference identity instead of guessing its target', () => {
    expect(() =>
      parseReferenceDriftDetails([
        { item_id: 'item', document_id: 'doc', chunk_id: 'chunk', reason: 'mismatch', expected: {} },
      ]),
    ).toThrow()
  })
})
