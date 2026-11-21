import { describe, expect, it } from 'vitest'
import { parseHardcaseDiscovery } from './evidence-hardcases'

const candidate = {
  question_hash: 'hash',
  cluster_size: 0,
  feedback_ids: [],
  request_ids: [],
  retrieval_config_hash: '',
  citations_count: 0,
  retrieval_error_kinds: {},
  rag_config_template: { template_key: 'policy', version: null, patch_hash: '' },
  opaque: { kept: false },
}
function discovery() {
  return {
    generated_at: '2026-11-16T00:00:00Z',
    enabled: true,
    window_minutes: 10080,
    max_bytes: 100000,
    truncated: false,
    feedback_scanned: 0,
    trace_index_size: 0,
    candidates: [candidate],
  }
}

describe('hardcase discovery response', () => {
  it('keeps a null template version distinct from an actual zero version', () => {
    const source = discovery()
    expect(parseHardcaseDiscovery(source)).toEqual(source)
    expect(
      parseHardcaseDiscovery({ ...source, candidates: [{ ...candidate, rag_config_template: { version: 0 } }] })
        .candidates[0].rag_config_template?.version,
    ).toBe(0)
  })
  it.each([false, '', '2'])('rejects an invalid template version %j without inventing a version', (version) => {
    expect(() =>
      parseHardcaseDiscovery({ ...discovery(), candidates: [{ ...candidate, rag_config_template: { version } }] }),
    ).toThrow()
  })
  it('distinguishes a real empty candidate set from a missing candidate list', () => {
    expect(parseHardcaseDiscovery({ ...discovery(), candidates: [] }).candidates).toEqual([])
    expect(() => parseHardcaseDiscovery({ ...discovery(), candidates: undefined })).toThrow()
  })
  it.each([{ question_hash: '' }, { feedback_ids: [''] }, { request_ids: [''] }])(
    'rejects an unusable pointer instead of rendering a silent action (%j)',
    (fields) => {
      expect(() => parseHardcaseDiscovery({ ...discovery(), candidates: [{ ...candidate, ...fields }] })).toThrow()
    },
  )
})
