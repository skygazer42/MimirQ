import type { Page, Route } from '@playwright/test'

type MockParsingDocument = {
  id: string
  filename: string
  file_type: string
  file_size: number
  status: string
  created_at: string
  updated_at: string
  error_message: string | null
  metadata?: Record<string, unknown>
  markdown_content?: string
  original_markdown_content?: string
  parse_duration_sec?: number | null
  parser_backend?: string
}

export type EnterpriseTelemetryMockState = {
  uploaded: boolean
  parsingDocuments?: MockParsingDocument[]
}

export const UPLOADED_DOCUMENT_ID = 'doc-e2e-1'
export const UPLOADED_DOCUMENT_FILENAME = 'enterprise-telemetry-sample.md'
export const PARSED_MARKDOWN = [
  '# Enterprise Telemetry Sample',
  '',
  'This markdown validates the upload -> parse -> chat smoke path.',
  '',
  '- request id propagation',
  '- offline shell caching',
  '- web vitals reporting',
].join('\n')

export async function installDeterministicRandom(page: Page) {
  await page.addInitScript(() => {
    let seed = 42
    Math.random = () => {
      seed = (seed * 1664525 + 1013904223) % 0x100000000
      return seed / 0x100000000
    }
  })
}

export async function installCommonApiMocks(page: Page, state: EnterpriseTelemetryMockState) {
  const getParsingDocuments = () => state.parsingDocuments ?? []

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname
    const method = request.method()

    if (pathname === '/api/v1/meta' && method === 'GET') {
      return fulfillJson(route, {
        name: 'MimirQ API',
        api_version: 'e2e',
        build: { sha: 'e2e1234' },
        features: {
          auth_mode: 'header',
          vector_backend: 'memory',
          task_queue_enabled: false,
        },
      })
    }

    if (pathname === '/api/v1/health/ready' && method === 'GET') {
      return fulfillJson(route, {
        ok: true,
        database: { status: 'ready' },
        vector: { status: 'ready', backend: 'memory' },
        redis: { status: 'disabled' },
        minio: { status: 'disabled' },
      })
    }

    if (pathname === '/api/v1/settings' && method === 'GET') {
      return fulfillJson(route, {
        rag: {
          retrieval_top_k: 5,
          similarity_threshold: 0.7,
        },
      })
    }

    if (pathname === '/api/v1/prompt-templates' && method === 'GET') {
      return fulfillJson(route, {
        items: [],
        total: 0,
      })
    }

    if ((pathname === '/api/v1/datasets' || pathname === '/api/v1/datasets/') && method === 'GET') {
      return fulfillJson(route, {
        items: [],
        total: 0,
      })
    }

    if ((pathname === '/api/v1/parsing/documents' || pathname === '/api/v1/parsing/documents/') && method === 'GET') {
      const parsingDocuments = getParsingDocuments()
      return fulfillJson(route, {
        items: parsingDocuments.map((document) => buildParsingDocumentSummary(document)),
        total: parsingDocuments.length,
      })
    }

    if ((pathname === '/api/v1/parsing/documents' || pathname === '/api/v1/parsing/documents/') && method === 'POST') {
      const uploadedDocument = buildParsingDocument({
        status: 'uploaded',
      })
      state.uploaded = true
      state.parsingDocuments = [
        ...getParsingDocuments().filter((document) => document.id !== uploadedDocument.id),
        uploadedDocument,
      ]
      return fulfillJson(route, buildParsingDocumentSummary(uploadedDocument))
    }

    if (pathname === `/api/v1/parsing/documents/${UPLOADED_DOCUMENT_ID}/parse` && method === 'POST') {
      const parsedDocument = buildParsingDocument({
        status: 'completed',
        markdown_content: PARSED_MARKDOWN,
        original_markdown_content: PARSED_MARKDOWN,
        parse_duration_sec: 1.2,
      })
      state.parsingDocuments = [
        ...getParsingDocuments().filter((document) => document.id !== parsedDocument.id),
        parsedDocument,
      ]
      return fulfillJson(route, {
        document_id: parsedDocument.id,
        parser_backend: parsedDocument.parser_backend || 'auto',
        markdown_content: parsedDocument.markdown_content,
        original_markdown_content: parsedDocument.original_markdown_content,
        parse_duration_sec: parsedDocument.parse_duration_sec,
        stats: {
          page_count: 1,
          table_count: 0,
          image_count: 0,
          block_count: 3,
        },
        pdf_quality: null,
        quality_gate: {
          grade: 'pass',
          reasons: [],
          evidence: {
            text_quality: {
              content_chars: PARSED_MARKDOWN.length,
              density: 0.95,
              replacement_ratio: 0,
            },
            parse_quality: {
              score: 0.98,
            },
          },
        },
      })
    }

    if (pathname === `/api/v1/parsing/documents/${UPLOADED_DOCUMENT_ID}/content` && method === 'GET') {
      const document = getParsingDocuments().find((entry) => entry.id === UPLOADED_DOCUMENT_ID)
      return fulfillJson(route, {
        document_id: UPLOADED_DOCUMENT_ID,
        parser_backend: document?.parser_backend || 'auto',
        markdown_content: document?.markdown_content || '',
        original_markdown_content: document?.original_markdown_content || '',
        parse_duration_sec: document?.parse_duration_sec || null,
        stats: {
          page_count: 1,
          table_count: 0,
          image_count: 0,
          block_count: 3,
        },
        pdf_quality: null,
        quality_gate: null,
      })
    }

    if (pathname === '/api/v1/documents/stats' && method === 'GET') {
      const total = state.uploaded ? 1 : 0
      return fulfillJson(route, {
        total,
        total_chunks: total ? 3 : 0,
        total_size: total ? 1024 : 0,
        by_status: state.uploaded ? { completed: 1 } : {},
      })
    }

    if ((pathname === '/api/v1/documents' || pathname === '/api/v1/documents/') && method === 'GET') {
      return fulfillJson(route, {
        items: state.uploaded ? [buildUploadedDocument()] : [],
        total: state.uploaded ? 1 : 0,
      })
    }

    if (pathname === '/api/v1/documents/upload-batch' && method === 'POST') {
      state.uploaded = true
      return fulfillJson(route, {
        total: 1,
        successful_count: 1,
        failed_count: 0,
        successful: [
          {
            document_id: UPLOADED_DOCUMENT_ID,
            filename: UPLOADED_DOCUMENT_FILENAME,
            source_path: UPLOADED_DOCUMENT_FILENAME,
          },
        ],
        failed: [],
      })
    }

    if (pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/status` && method === 'GET') {
      return fulfillJson(route, {
        status: 'completed',
        processing_progress: 100,
        current_stage: 'indexed',
        error_message: null,
      })
    }

    if (pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}` && method === 'GET') {
      return fulfillJson(route, buildUploadedDocument())
    }

    if (pathname === '/api/v1/chat/stream' && method === 'POST') {
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: {
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
          'X-Request-ID': 'req-chat-e2e-1',
          'X-Conversation-ID': 'conv-e2e-1',
        },
        body: [
          'data: {"type":"token","data":{"content":"已完成"}}\n\n',
          'data: {"type":"token","data":{"content":"智能对话验证。"}}\n\n',
          'data: {"type":"done","request_id":"req-chat-e2e-1","data":{"conversation_id":"conv-e2e-1","assistant_message_id":"assistant-e2e-1","request_id":"req-chat-e2e-1"}}\n\n',
        ].join(''),
      })
    }

    if (pathname === '/api/v1/observability/frontend-vitals' && method === 'POST') {
      return route.fulfill({ status: 204, body: '' })
    }

    return fulfillJson(route, {})
  })
}

export async function installRagvizApiMocks(page: Page) {
  await page.route('**/api/v1/ragviz/similarity/collections', async (route) => {
    await fulfillJson(route, {
      collections: [
        { id: 'alpha', label: 'Alpha Docs', kind: 'documents', count: 2 },
        { id: 'beta', label: 'Beta Docs', kind: 'documents', count: 2 },
      ],
    })
  })

  await page.route('**/api/v1/ragviz/similarity/calculate', async (route) => {
    await fulfillJson(route, {
      success: true,
      result: {
        matrix: [
          [0.93, 0.42],
          [0.58, 0.84],
        ],
        x_data: [{ document: 'Alpha 1' }, { document: 'Alpha 2' }],
        y_data: [{ document: 'Beta 1' }, { document: 'Beta 2' }],
        x_available_fields: ['document'],
        y_available_fields: ['document'],
        metadata: {
          x_collection: 'alpha',
          y_collection: 'beta',
        },
      },
    })
  })
}

function buildUploadedDocument() {
  return {
    id: UPLOADED_DOCUMENT_ID,
    dataset_id: null,
    filename: UPLOADED_DOCUMENT_FILENAME,
    file_type: 'md',
    file_size: 1024,
    status: 'completed',
    processing_progress: 100,
    current_stage: 'indexed',
    error_message: null,
    chunk_count: 3,
    created_at: '2026-03-27T00:00:00.000Z',
    updated_at: '2026-03-27T00:00:00.000Z',
    archived_at: null,
    disabled_at: null,
    metadata: {
      source_path: UPLOADED_DOCUMENT_FILENAME,
    },
  }
}

function buildParsingDocument(overrides: Partial<MockParsingDocument> = {}): MockParsingDocument {
  return {
    id: UPLOADED_DOCUMENT_ID,
    filename: UPLOADED_DOCUMENT_FILENAME,
    file_type: 'md',
    file_size: 1024,
    status: 'uploaded',
    created_at: '2026-03-27T00:00:00.000Z',
    updated_at: '2026-03-27T00:00:00.000Z',
    error_message: null,
    metadata: {
      parser_backend_requested: 'auto',
      parser_backend: 'auto',
    },
    parser_backend: 'auto',
    markdown_content: '',
    original_markdown_content: '',
    parse_duration_sec: null,
    ...overrides,
  }
}

function buildParsingDocumentSummary(document: MockParsingDocument) {
  return {
    id: document.id,
    filename: document.filename,
    file_type: document.file_type,
    file_size: document.file_size,
    status: document.status,
    created_at: document.created_at,
    updated_at: document.updated_at,
    error_message: document.error_message,
    metadata: document.metadata || {
      parser_backend_requested: document.parser_backend || 'auto',
      parser_backend: document.parser_backend || 'auto',
    },
  }
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}
