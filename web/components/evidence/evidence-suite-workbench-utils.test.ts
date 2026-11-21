import { describe, expect, it } from 'vitest'
import { parseEvidenceCitations } from '@/lib/evidence-citations'
import { buildReferenceSources, parseEvidenceImportPack } from './evidence-suite-workbench-utils'

describe('evidence records and import data contracts', () => {
  it('retains partial citations, original whitespace, nulls and opaque fields', () => {
    const citations = [
      {
        document_id: 'doc',
        chunk_id: 'chunk',
        chunk_content: '',
        page_number: 0,
        relevance_score: null,
        metadata: { kept: false },
      },
      { document_id: 'minimal' },
    ]
    expect(parseEvidenceCitations(citations)).toEqual(citations)
  })

  it.each([false, true, '', '0.8'])('rejects an invalid numeric score %j without coercing it', (relevance_score) => {
    expect(() => parseEvidenceCitations([{ document_id: 'doc', document_name: 'name', relevance_score }])).toThrow()
  })

  it.each([{}, { citations: false }, { citations: [], selected_chunk_ids: [false] }])(
    'rejects an invalid import object %j',
    (pack) => {
      expect(() => parseEvidenceImportPack(pack)).toThrow()
    },
  )

  it('keeps an explicit empty selection and every raw pack field', () => {
    const pack = { version: 1, citations: [], selected_chunk_ids: [], retrieval_profile: '', extra: { flag: false } }
    expect(parseEvidenceImportPack(pack)).toEqual(pack)
  })

  it('makes reference metadata respect its actual API contract without rewriting the snapshot', () => {
    const citations = parseEvidenceCitations([
      {
        document_id: 'doc',
        document_name: 'name',
        chunk_id: 'chunk',
        chunk_content: '',
        relevance_score: 0,
        page_number: 0,
        chunk_index: 0,
        header_path: '',
      },
    ])
    expect(buildReferenceSources(citations, new Set(['chunk']))).toMatchObject([
      { document_id: 'doc', chunk_id: 'chunk', chunk_index: 0, quote: '', label: '' },
    ])
    expect(buildReferenceSources(citations, new Set(['chunk']))[0].page_number).toBeUndefined()
    expect(citations[0].page_number).toBe(0)
  })

  it('limits the optional quote and label in server character units without cutting a surrogate pair', () => {
    const content = '甲'.repeat(1999) + '😀尾'
    const label = '标'.repeat(99) + '😀尾'
    const citations = parseEvidenceCitations([
      {
        document_id: 'doc',
        document_name: 'name',
        chunk_id: 'chunk',
        chunk_content: content,
        header_path: label,
        relevance_score: 0,
      },
    ])
    const [reference] = buildReferenceSources(citations, new Set(['chunk']))
    expect(reference.quote).toBe('甲'.repeat(1999) + '😀')
    expect(reference.label).toBe('标'.repeat(99) + '😀')
    expect(citations[0].chunk_content).toBe(content)
  })

  it('keeps hierarchy and record identity fields in the saved reference', () => {
    const citation = {
      document_id: 'doc',
      chunk_id: 'chunk',
      family_collapse_key: '',
      hierarchy_family_key: 'family',
      record_identity: { row: 0, flag: false },
      semantic_keys: ['equivalent'],
    }
    expect(buildReferenceSources(parseEvidenceCitations([citation]), new Set(['chunk']))[0]).toMatchObject(citation)
  })
})
