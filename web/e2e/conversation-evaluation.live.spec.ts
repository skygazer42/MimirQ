import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 300_000

type LiveDocument = {
  id?: string
  status?: string
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function apiBaseUrl(): string {
  return String(
    process.env.PLAYWRIGHT_LIVE_API_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      'http://127.0.0.1:8000'
  ).replace(/\/+$/, '')
}

function liveHeaders(): Record<string, string> {
  return {
    'X-Tenant-ID':
      process.env.PLAYWRIGHT_LIVE_TENANT_ID ||
      process.env.NEXT_PUBLIC_TENANT_ID ||
      DEFAULT_TENANT_ID,
    'X-Account-ID':
      process.env.PLAYWRIGHT_LIVE_USER_ID ||
      process.env.NEXT_PUBLIC_USER_ID ||
      DEFAULT_USER_ID,
    'X-User-ID':
      process.env.PLAYWRIGHT_LIVE_USER_ID ||
      process.env.NEXT_PUBLIC_USER_ID ||
      DEFAULT_USER_ID,
  }
}

async function installLiveAuth(page: Page) {
  const headers = liveHeaders()
  await page.addInitScript(
    ({ tenantId, userId }) => {
      window.localStorage.setItem('mimirq_tenant_id', tenantId)
      window.localStorage.setItem('mimirq_user_id', userId)
    },
    {
      tenantId: headers['X-Tenant-ID'],
      userId: headers['X-User-ID'],
    }
  )
}

async function createLiveDataset(
  request: APIRequestContext,
  name: string
): Promise<string> {
  const response = await request.post(`${apiBaseUrl()}/api/v1/datasets/`, {
    headers: liveHeaders(),
    data: {
      name,
      description: 'Playwright live conversation evaluation dataset.',
      permission: 'all_team_members',
      default_parser_backend: 'auto',
      default_chunk_strategy: 'langchain_recursive',
      pipeline: {
        governance_enabled: true,
        persist_parsed_content: true,
        persist_parsed_content_max_chars: 200000,
        chunk_size: 1000,
        chunk_overlap: 200,
        chunk_vector_enabled: true,
        bm25_index_enabled: true,
        kg_enabled: false,
        event_vector_enabled: false,
        entity_vector_enabled: false,
      },
    },
  })
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { id?: string; dataset_id?: string }
  const datasetId = String(body.id || body.dataset_id || '')
  expect(datasetId).toMatch(/\S/)
  return datasetId
}

async function deleteLiveDataset(
  request: APIRequestContext,
  datasetId: string
): Promise<void> {
  const purgeResponse = await request.post(
    `${apiBaseUrl()}/api/v1/datasets/${datasetId}/purge?dry_run=false&max_delete=1000`,
    {
      headers: liveHeaders(),
      data: {},
    }
  )
  expect(purgeResponse.ok()).toBe(true)

  const response = await request.delete(
    `${apiBaseUrl()}/api/v1/datasets/${datasetId}`,
    { headers: liveHeaders() }
  )
  expect([200, 204]).toContain(response.status())
}

async function deleteConversation(
  request: APIRequestContext,
  conversationId: string
): Promise<void> {
  const response = await request.delete(
    `${apiBaseUrl()}/api/v1/chat/conversations/${conversationId}`,
    { headers: liveHeaders() }
  )
  expect([200, 204]).toContain(response.status())
}

async function uploadCompletedDocument(
  request: APIRequestContext,
  {
    datasetId,
    filename,
    content,
  }: {
    datasetId: string
    filename: string
    content: string
  }
): Promise<string> {
  const response = await request.post(`${apiBaseUrl()}/api/v1/documents/upload`, {
    headers: liveHeaders(),
    multipart: {
      dataset_id: datasetId,
      parser_backend: 'basic',
      chunk_strategy: 'langchain_recursive',
      file: {
        name: filename,
        mimeType: 'text/markdown',
        buffer: Buffer.from(content, 'utf8'),
      },
    },
  })
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { id?: string; document_id?: string }
  const documentId = String(body.id || body.document_id || '')
  expect(documentId).toMatch(/\S/)
  return documentId
}

async function fetchLiveDocument(
  request: APIRequestContext,
  documentId: string
): Promise<LiveDocument> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/documents/${documentId}`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as LiveDocument
}

async function waitForLiveDocumentStatus(
  request: APIRequestContext,
  documentId: string,
  expectedStatus: string
): Promise<void> {
  await expect
    .poll(async () => {
      const current = await fetchLiveDocument(request, documentId)
      return String(current.status || '').toLowerCase()
    }, {
      timeout: 180_000,
    })
    .toBe(expectedStatus)
}

async function createConversationViaChat(
  request: APIRequestContext,
  {
    datasetId,
    message,
  }: {
    datasetId: string
    message: string
  }
): Promise<string> {
  const response = await request.post(`${apiBaseUrl()}/api/v1/chat`, {
    headers: {
      ...liveHeaders(),
      'Content-Type': 'application/json',
    },
    data: {
      message,
      dataset_id: datasetId,
      stream: false,
      rag_config: {
        top_k: 4,
        score_threshold: 0.0,
        retrieval_mode: 'keyword',
        enable_reranker: false,
        enable_multi_query: false,
        enable_hyde: false,
        enable_query_decomposition: false,
        answer_mode: 'extractive',
        max_tokens: 300,
      },
    },
  })
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { conversation_id?: string }
  const conversationId = String(body.conversation_id || '')
  expect(conversationId).toMatch(/\S/)
  return conversationId
}

async function listRagasRuns(
  request: APIRequestContext,
  conversationId: string
): Promise<Array<{ id?: string }>> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/evaluations/ragas/runs?limit=50&conversation_id=${encodeURIComponent(conversationId)}`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as {
    items?: Array<{ id?: string }>
  }
  return Array.isArray(body.items) ? body.items : []
}

test.describe('live conversation evaluation workbench', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('starts a real conversation evaluation run on the deployed page host', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const datasetName = `playwright-conversation-eval-${Date.now()}`
    const uniqueToken = `CONV-ANCHOR-${Date.now()}`
    const filename = `conversation-eval-${Date.now()}.md`
    const question = `Who owns token ${uniqueToken}?`
    const markdown = [
      '# Conversation Evaluation Probe',
      '',
      `Token ${uniqueToken} belongs only to this document.`,
      'Owner: Connie Run.',
      '',
    ].join('\n')

    let datasetId = ''
    let conversationId = ''

    try {
      datasetId = await createLiveDataset(request, datasetName)
      const documentId = await uploadCompletedDocument(request, {
        datasetId,
        filename,
        content: markdown,
      })
      await waitForLiveDocumentStatus(request, documentId, 'completed')
      conversationId = await createConversationViaChat(request, {
        datasetId,
        message: question,
      })

      const beforeRuns = await listRagasRuns(request, conversationId)
      const beforeCount = beforeRuns.length

      await page.goto(
        `/evaluations?conversation_id=${encodeURIComponent(conversationId)}`,
        { waitUntil: 'networkidle' }
      )
      await expect(page.getByRole('heading', { name: '实时会话评分' })).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('当前对话')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByRole('button', { name: '开始评测' })).toBeEnabled({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.getByRole('button', { name: '开始评测' }).click()

      let latestRunId = ''
      await expect
        .poll(async () => {
          const runs = await listRagasRuns(request, conversationId)
          latestRunId = String(runs[0]?.id || '')
          return runs.length
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBeGreaterThan(beforeCount)

      const runIdShort = latestRunId.slice(0, 8)
      expect(runIdShort).toMatch(/\S/)
      await expect(
        page.getByRole('button', {
          name: new RegExp(
            `${escapeRegExp(question)}[\\s\\S]*(运行中|已完成|失败)`
          ),
        })
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      expect(pageErrors).toEqual([])
    } finally {
      if (conversationId) {
        await deleteConversation(request, conversationId)
      }
      if (datasetId) {
        await deleteLiveDataset(request, datasetId)
      }
    }
  })
})
