import { afterEach, describe, expect, it, vi } from 'vitest'

const apiCoreMock = vi.hoisted(() => ({
  apiClient: { post: vi.fn() },
  openapiRequest: vi.fn(),
}))

vi.mock('@/lib/api/core', () => apiCoreMock)

import { ragApi, retrievalApi } from './api/rag'

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

describe('retrievalApi payload routing', () => {
  it('posts explain requests to the retrieval explain endpoint', async () => {
    const payload = { query: '为什么召回下降', retrieval_only: true }
    apiCoreMock.apiClient.post.mockResolvedValueOnce({ data: { ok: true } })

    await expect(retrievalApi.explain(payload)).resolves.toEqual({ ok: true })
    expect(apiCoreMock.apiClient.post).toHaveBeenCalledWith(
      '/retrieval/explain',
      payload,
      expect.objectContaining({ timeout: expect.any(Number) })
    )
  })

  it('posts config-hash requests to the retrieval config-hash endpoint', async () => {
    const payload = {
      rag_config: { retrieval_profile: 'grounded_strict', top_k: 20 },
      include_runtime_defaults: true,
    }
    apiCoreMock.apiClient.post.mockResolvedValueOnce({
      data: { hash: 'cfg-123' },
    })

    await expect(retrievalApi.configHash(payload)).resolves.toEqual({
      hash: 'cfg-123',
    })
    expect(apiCoreMock.apiClient.post).toHaveBeenCalledWith(
      '/retrieval/config-hash',
      payload
    )
  })
})
