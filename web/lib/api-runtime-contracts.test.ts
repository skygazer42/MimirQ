import { AxiosError, AxiosHeaders } from 'axios'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { citationListSchema } from './citations'

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
let connectorApi: typeof import('./api/connectors').connectorApi

const SAMPLE_UUID = '00000000-0000-0000-0000-000000000001'

describe('API runtime contracts', () => {
  beforeAll(async () => {
    ;({ parsingApi } = await import('./api/parsing'))
    ;({ documentApi } = await import('./api/documents'))
    ;({ chatApi } = await import('./api/chat'))
    ;({ ragApi } = await import('./api/rag'))
    ;({ connectorApi } = await import('./api/connectors'))
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
          edited: false,
          stats: { page_count: 1 },
          quality_gate: { grade: 'warn', reasons: ['ocr review'] },
          elements: [
            {
              id: 'table:1:0',
              kind: 'table',
              page: 1,
              pages: [1, 2],
              text: '| A | B |',
            },
          ],
        }).success,
      ).toBe(true)
      expect(requestArgs?.responseSchema.safeParse({ document_id: 42 }).success).toBe(false)
    }
  })

  it('passes a runtime response schema for parsing extraction boundaries', async () => {
    openapiRequestMock.mockResolvedValueOnce({ document_id: SAMPLE_UUID, mode: 'schema', result: {} })

    await parsingApi.extract(SAMPLE_UUID, {
      mode: 'schema',
      max_evidence: 1,
      schema_: {
        company_name: {
          type: 'string',
          source_kind: 'seal',
        },
      },
    })

    const requestArgs = openapiRequestMock.mock.calls.at(-1)?.[0]
    expect(requestArgs?.responseSchemaName).toBe('ParsingExtractResponse')
    expect(
      requestArgs?.responseSchema.safeParse({
        document_id: SAMPLE_UUID,
        mode: 'schema',
        result: {
          company_name: {
            value: '杭州测试科技有限公司',
            confidence: 0.97,
            strategy: 'element_match',
            evidence: [
              {
                element_id: 'seal:2:0',
                kind: 'seal',
                page: 2,
                pages: [2],
                visual_kind: 'stamp',
                bbox: { x0: 10, y0: 20, x1: 60, y1: 70 },
                text: '杭州测试科技有限公司',
                score: 0.97,
              },
            ],
          },
        },
      }).success,
    ).toBe(true)
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
      }).success,
    ).toBe(true)
    expect(requestArgs?.responseSchema.safeParse({ document_id: null }).success).toBe(false)
  })

  it('validates the actual HTTP chat response and rejects missing required fields', async () => {
    apiClientMock.post.mockResolvedValueOnce({
      status: 200,
      headers: {},
      data: {
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
        total_tokens: 0,
        total_chars: 5,
        structured: false,
      },
    })
    await expect(chatApi.chat({ message: 'hello', stream: false })).resolves.toMatchObject({
      content: 'hello',
      request_id: 'rid-chat',
      total_tokens: 0,
    })
    apiClientMock.post.mockResolvedValueOnce({
      status: 200,
      headers: {},
      data: { conversation_id: SAMPLE_UUID, content: 'missing fields' },
    })
    await expect(chatApi.chat({ message: 'hello', stream: false })).rejects.toThrow('invalid ChatResponse response')
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
      }).success,
    ).toBe(true)
    expect(requestArgs?.responseSchema.safeParse({ query_for_retrieval: 1, citations: 'nope' }).success).toBe(false)
  })

  it('keeps supported connectors when a cached catalog still contains removed imports', async () => {
    openapiRequestMock.mockResolvedValueOnce([
      { id: 'url_batch', name: 'URL batch' },
      { id: 'confluence_space', name: 'Confluence' },
      { id: 'github_repo', name: 'GitHub' },
      { id: 'drive_files', name: 'Google Drive' },
      { id: 'unknown_connector', name: 'Unknown' },
    ])

    await expect(connectorApi.listConnectors()).resolves.toEqual([
      { id: 'url_batch', name: 'URL batch' },
      { id: 'confluence_space', name: 'Confluence' },
    ])
  })

  it('drops retired citation scores without losing current scores or plugin metadata', () => {
    const citation = {
      document_id: SAMPLE_UUID,
      document_name: 'Doc',
      chunk_content: 'Chunk body',
      relevance_score: 0.9,
      vector_score: 0.8,
      bm25_score: 0.6,
      lexical_score: 0.4,
      rerank_score: 0.7,
      sparse_score: 0.99,
      colbert_score: 0.98,
      metadata: { plugin: { confidence: 0.85, source: 'custom' } },
      hierarchy_family_key: 'section-1',
      clean_docx_url: '/documents/clean.docx',
    }

    const [parsed] = citationListSchema.parse([citation])

    expect(parsed).not.toHaveProperty('sparse_score')
    expect(parsed).not.toHaveProperty('colbert_score')
    expect(parsed).toMatchObject({
      vector_score: 0.8,
      bm25_score: 0.6,
      lexical_score: 0.4,
      rerank_score: 0.7,
      metadata: citation.metadata,
      hierarchy_family_key: citation.hierarchy_family_key,
      clean_docx_url: citation.clean_docx_url,
    })
    expect(citation).toHaveProperty('sparse_score', 0.99)
    expect(citation).toHaveProperty('colbert_score', 0.98)
  })

  it('drops retired scores from trace citations while preserving current evidence', async () => {
    apiClientMock.get.mockResolvedValueOnce({
      status: 200,
      headers: {},
      data: {
        enabled: true,
        path: 'trace.jsonl',
        window_minutes: 60,
        truncated: false,
        returned: 1,
        items: [
          {
            schema_version: 1,
            ts_ms: 1,
            retrieval: {},
            rerank: { enabled: true },
            citations: [
              {
                document_id: SAMPLE_UUID,
                vector_score: 0.8,
                bm25_score: 0.6,
                lexical_score: 0.4,
                rerank_score: 0.7,
                sparse_score: 0.99,
                colbert_score: 0.98,
                kg_path_provenance: { plugin: { source: 'custom' } },
              },
            ],
            citations_count: 1,
            steps: [],
          },
        ],
      },
    })

    const response = await chatApi.getRagTraces(SAMPLE_UUID)
    const [citation] = response.items[0].citations

    expect(citation).not.toHaveProperty('sparse_score')
    expect(citation).not.toHaveProperty('colbert_score')
    expect(citation).toMatchObject({
      document_id: SAMPLE_UUID,
      vector_score: 0.8,
      bm25_score: 0.6,
      lexical_score: 0.4,
      rerank_score: 0.7,
      kg_path_provenance: { plugin: { source: 'custom' } },
    })
  })

  it('requires all rule sections and preserves the values used for whole-section writes', async () => {
    const { industryRulesApi } = await import('./api/industry-rules')
    const ruleset = {
      name: 'industrial_control',
      glossary_count: 1,
      pattern_count: 1,
      intent_count: 0,
      glossary: Object.fromEntries([['__proto__', ['A, B']]]),
      patterns: [{ keywords: ['报警'], enabled: false, priority: 0, extension: null }],
      intents: [],
    }
    const data = { schema: 'mimirq.industry_rules_ruleset.v1', ruleset }
    const signal = new AbortController().signal
    apiClientMock.get
      .mockResolvedValueOnce({ data, headers: {}, status: 200 })
      .mockResolvedValueOnce({
        data: { ...data, ruleset: { ...ruleset, patterns: undefined } },
        headers: {},
        status: 200,
      })
      .mockResolvedValueOnce({ data: { ...data, ruleset: { ...ruleset, name: 'other' } }, headers: {}, status: 200 })

    const response = await industryRulesApi.getRuleset(ruleset.name, { signal })
    expect(apiClientMock.get).toHaveBeenCalledWith('/industry-rules/rulesets/industrial_control', { signal })
    expect(Object.hasOwn(response.ruleset.glossary, '__proto__')).toBe(true)
    expect(response.ruleset).toEqual(ruleset)
    await expect(industryRulesApi.getRuleset(ruleset.name)).rejects.toThrow('invalid IndustryRulesetDetailResponse')
    await expect(industryRulesApi.getRuleset(ruleset.name)).rejects.toThrow('返回的规则集与请求不一致')
  })

  it('requires the cleanup counters and verifies that the receipt matches the requested account and mode', async () => {
    const { rtbfApi } = await import('./api/rtbf')
    const request = { subject_account_id: 'account-a', dry_run: false, max_docs: 100, max_retries: 0 }
    const receipt = {
      schema: 'mimirq.rtbf_cascade.v1',
      subject_account_id: 'account-a',
      dry_run: false,
      eligible: 0,
      deleted: 0,
      errors: 0,
      cache_invalidations: 0,
      documents: [],
    }
    apiClientMock.post
      .mockResolvedValueOnce({ data: receipt, headers: {}, status: 200 })
      .mockResolvedValueOnce({ data: { ...receipt, eligible: undefined }, headers: {}, status: 200 })
      .mockResolvedValueOnce({ data: { ...receipt, subject_account_id: 'account-b' }, headers: {}, status: 200 })
      .mockResolvedValueOnce({ data: { ...receipt, dry_run: true }, headers: {}, status: 200 })

    await expect(rtbfApi.request(request)).resolves.toEqual(receipt)
    await expect(rtbfApi.request(request)).rejects.toThrow('invalid RtbfCascadeResponse')
    await expect(rtbfApi.request(request)).rejects.toThrow('返回的目标账号或执行模式与请求不一致')
    await expect(rtbfApi.request(request)).rejects.toThrow('返回的目标账号或执行模式与请求不一致')
  })

  it('reads backend readiness details from a structured 503 and propagates unrelated failures', async () => {
    const { healthApi } = await import('./api/health')
    const readiness = { ok: false, status: 'unready' }
    const details = {
      ...readiness,
      database: { ok: false },
      vector: { ok: true },
      redis: { ok: true },
      minio: { ok: true },
      time: '2026-11-19T00:00:00Z',
      vector_backend: 'milvus',
      use_langgraph_pipeline: false,
      task_queue: {},
      uploads: {},
    }
    function unavailable(data: unknown) {
      return new AxiosError('Service unavailable', AxiosError.ERR_BAD_RESPONSE, undefined, undefined, {
        config: { headers: new AxiosHeaders() },
        data,
        headers: {},
        status: 503,
        statusText: 'Service unavailable',
      })
    }
    const proxyError = unavailable({ detail: 'Service unavailable' })
    openapiRequestMock
      .mockRejectedValueOnce(unavailable(readiness))
      .mockRejectedValueOnce(unavailable(details))
      .mockRejectedValueOnce(proxyError)

    await expect(healthApi.ready()).resolves.toEqual(readiness)
    await expect(healthApi.details()).resolves.toMatchObject(details)
    await expect(healthApi.details()).rejects.toBe(proxyError)
  })
})
