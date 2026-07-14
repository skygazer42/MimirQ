import { afterEach, describe, expect, it, vi } from 'vitest'

const apiCoreMock = vi.hoisted(() => ({
  apiClient: { post: vi.fn() },
  openapiRequest: vi.fn(),
}))

vi.mock('@/lib/api/core', () => apiCoreMock)

import { ragApi } from './api/rag'

afterEach(() => {
  vi.clearAllMocks()
})

describe('ragApi.retrieveEvidence', () => {
  it('posts the request to the retrieval-only endpoint and returns its payload', async () => {
    const request = { query: 'What is the policy?', dataset_id: 'dataset-1', top_k: 5 }
    const response = {
      query_for_retrieval: request.query,
      citations: [],
      schema: 'mimirq.evidence.v1',
      has_evidence: false,
      abstain_triggered: true,
    }
    apiCoreMock.openapiRequest.mockResolvedValue(response)

    await expect(ragApi.retrieveEvidence(request)).resolves.toEqual(response)
    expect(apiCoreMock.openapiRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        path: '/api/v1/rag/retrieve',
        method: 'post',
        body: request,
        responseSchemaName: 'EvidenceRetrieveResponse',
      })
    )
  })
})
