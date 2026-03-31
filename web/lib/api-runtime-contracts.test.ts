import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const openapiRequestMock = vi.hoisted(() => vi.fn())
const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}))

vi.mock('@/lib/api/core', () => ({
  apiClient: apiClientMock,
  openapiRequest: openapiRequestMock,
}))

let parsingApi: typeof import('./api/parsing').parsingApi
let documentApi: typeof import('./api/documents').documentApi
let chatApi: typeof import('./api/chat').chatApi
let ragApi: typeof import('./api/rag').ragApi

const SAMPLE_UUID = '00000000-0000-0000-0000-000000000001'

describe('API runtime contracts', () => {
  beforeAll(async () => {
    ;({ parsingApi } = await import('./api/parsing'))
    ;({ documentApi } = await import('./api/documents'))
    ;({ chatApi } = await import('./api/chat'))
    ;({ ragApi } = await import('./api/rag'))
  })

  beforeEach(() => {
    openapiRequestMock.mockReset()
    apiClientMock.get.mockReset()
    apiClientMock.post.mockReset()
    apiClientMock.patch.mockReset()
  })

  it('passes a runtime response schema for parsing parse/content boundaries', async () => {
    openapiRequestMock
      .mockResolvedValueOnce({ document_id: SAMPLE_UUID })
      .mockResolvedValueOnce({ document_id: SAMPLE_UUID })
      .mockResolvedValueOnce({ document_id: SAMPLE_UUID })

    await parsingApi.parse(SAMPLE_UUID)
    await parsingApi.getContent(SAMPLE_UUID)
    await parsingApi.updateContent(SAMPLE_UUID, { markdown_content: '# Updated' })

    for (const requestArgs of openapiRequestMock.mock.calls.map((call) => call[0])) {
      expect(requestArgs?.responseSchemaName).toBe('ParsingContentResponse')
      expect(
        requestArgs?.responseSchema.safeParse({
          document_id: SAMPLE_UUID,
          parser_backend: 'marker',
          markdown_content: '# Parsed',
          original_markdown_content: '# Parsed',
          stats: { page_count: 1 },
          quality_gate: { grade: 'warn', reasons: ['ocr review'] },
        }).success
      ).toBe(true)
      expect(requestArgs?.responseSchema.safeParse({ document_id: 42 }).success).toBe(false)
    }
  })

  it('passes a runtime response schema for persisted document parsed content', async () => {
    openapiRequestMock.mockResolvedValueOnce({ document_id: SAMPLE_UUID })

    await documentApi.getParsedContent(SAMPLE_UUID)

    const requestArgs = openapiRequestMock.mock.calls[0]?.[0]
    expect(requestArgs?.responseSchemaName).toBe('DocumentParsedContentResponse')
    expect(
      requestArgs?.responseSchema.safeParse({
        document_id: SAMPLE_UUID,
        available: true,
        markdown_content: '# Stored',
        original_markdown_content: '# Original',
        persisted_meta: { source: 'pipeline' },
        markdown_truncated: false,
        original_markdown_truncated: false,
        max_chars: 1000,
      }).success
    ).toBe(true)
    expect(requestArgs?.responseSchema.safeParse({ document_id: null }).success).toBe(false)
  })

  it('passes a runtime response schema for chat responses', async () => {
    openapiRequestMock.mockResolvedValueOnce({
      conversation_id: SAMPLE_UUID,
      assistant_message_id: SAMPLE_UUID,
      request_id: 'rid-chat',
      content: 'hello',
    })

    await chatApi.chat({ message: 'hello', stream: false })

    const requestArgs = openapiRequestMock.mock.calls[0]?.[0]
    expect(requestArgs?.responseSchemaName).toBe('ChatResponse')
    expect(
      requestArgs?.responseSchema.safeParse({
        conversation_id: SAMPLE_UUID,
        assistant_message_id: SAMPLE_UUID,
        request_id: 'rid-chat',
        content: 'hello',
        citations: [
          {
            document_id: SAMPLE_UUID,
            document_name: 'Doc',
            chunk_content: 'Chunk body',
            relevance_score: 0.9,
          },
        ],
        metrics: { latency_ms: 12 },
      }).success
    ).toBe(true)
    expect(requestArgs?.responseSchema.safeParse({ conversation_id: SAMPLE_UUID, content: 'missing fields' }).success).toBe(false)
  })

  it('passes a runtime response schema for rag evidence responses', async () => {
    openapiRequestMock.mockResolvedValueOnce({
      query_for_retrieval: 'question',
      citations: [],
    })

    await ragApi.retrieveEvidence({ query: 'question', dataset_id: SAMPLE_UUID })

    const requestArgs = openapiRequestMock.mock.calls[0]?.[0]
    expect(requestArgs?.responseSchemaName).toBe('EvidenceRetrieveResponse')
    expect(
      requestArgs?.responseSchema.safeParse({
        query_for_retrieval: 'question',
        citations: [{ document_id: SAMPLE_UUID }],
        metrics: { top_k: 5 },
        has_evidence: true,
      }).success
    ).toBe(true)
    expect(requestArgs?.responseSchema.safeParse({ query_for_retrieval: 1, citations: 'nope' }).success).toBe(false)
  })
})
