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

type LiveChatResponse = {
  conversation_id?: string
  assistant_message_id?: string
  content?: string
}

type LiveFeedbackResponse = {
  id?: string
  extra?: Record<string, unknown>
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
      description: 'Playwright live feedback dataset.',
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

async function createLiveChat(
  request: APIRequestContext,
  {
    datasetId,
    message,
  }: {
    datasetId: string
    message: string
  }
): Promise<LiveChatResponse> {
  const response = await request.post(`${apiBaseUrl()}/api/v1/chat`, {
    headers: liveHeaders(),
    data: {
      message,
      dataset_id: datasetId,
      stream: false,
      rag_config: {
        top_k: 4,
        score_threshold: 0.0,
        retrieval_mode: 'hybrid',
        enable_reranker: false,
        enable_multi_query: false,
        enable_hyde: false,
        enable_query_decomposition: false,
        use_graph: false,
        answer_mode: 'extractive',
      },
    },
  })
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as LiveChatResponse
  expect(String(body.conversation_id || '')).toMatch(/\S/)
  expect(String(body.assistant_message_id || '')).toMatch(/\S/)
  return body
}

async function createLiveFeedback(
  request: APIRequestContext,
  {
    assistantMessageId,
    reason,
    expectedAnswer,
  }: {
    assistantMessageId: string
    reason: string
    expectedAnswer: string
  }
): Promise<string> {
  const response = await request.post(`${apiBaseUrl()}/api/v1/feedback/messages`, {
    headers: liveHeaders(),
    data: {
      message_id: assistantMessageId,
      rating: 2,
      reason,
      tags: ['playwright', 'feedback-live'],
      expected_answer: expectedAnswer,
      extra: {
        source: 'playwright-live-feedback',
      },
    },
  })
  expect([200, 201]).toContain(response.status())
  const body = (await response.json()) as LiveFeedbackResponse
  const feedbackId = String(body.id || '')
  expect(feedbackId).toMatch(/\S/)
  return feedbackId
}

async function fetchFeedbackRow(
  request: APIRequestContext,
  assistantMessageId: string
): Promise<LiveFeedbackResponse> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/feedback/messages?message_id=${encodeURIComponent(assistantMessageId)}&limit=10`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { items?: LiveFeedbackResponse[] }
  const row = (body.items || [])[0]
  expect(row).toBeTruthy()
  return row
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

test.describe('live feedback workbench', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('opens a real feedback detail and archives it from the deployed feedback page', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const datasetName = `playwright-feedback-${Date.now()}`
    const filename = `feedback-${Date.now()}.md`
    const markdown = [
      '# Feedback Workbench',
      '',
      'Payload checksum propagation must be preserved across the answer.',
      '',
      'The ideal answer should mention the checksum handoff explicitly.',
      '',
    ].join('\n')
    const uniqueReason = `playwright feedback ${Date.now()} missing payload checksum propagation`
    const expectedAnswer = 'The answer should mention payload checksum propagation explicitly.'
    const chatQuestion = 'What should the answer mention about payload checksum propagation?'

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

      const chat = await createLiveChat(request, {
        datasetId,
        message: chatQuestion,
      })
      conversationId = String(chat.conversation_id || '')
      const assistantMessageId = String(chat.assistant_message_id || '')
      await createLiveFeedback(request, {
        assistantMessageId,
        reason: uniqueReason,
        expectedAnswer,
      })

      await page.goto('/knowledge/feedback', { waitUntil: 'networkidle' })
      await expect(
        page.getByRole('heading', { name: '反馈分析中心' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      const searchInput = page.getByPlaceholder('搜索反馈 / 原因 / 标签 / 账号')
      await searchInput.fill(uniqueReason)

      const card = page.locator('article').filter({ hasText: uniqueReason }).first()
      await expect(card).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await expect(card).toContainText(uniqueReason, {
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await card.getByRole('button', { name: '查看详情' }).click()

      const detailDialog = page.getByRole('dialog')

      await expect(detailDialog.getByText('User Feedback')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(detailDialog.getByText(uniqueReason)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(detailDialog.getByText('Expected Output')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(detailDialog.getByText(expectedAnswer)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(detailDialog.getByText('AI Response')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await detailDialog.getByRole('button', { name: '关闭面板' }).click()

      const archiveButton = card.getByRole('button', { name: '标记已处理' })
      await archiveButton.evaluate((node) => {
        ;(node as HTMLButtonElement).click()
      })

      await expect
        .poll(async () => {
          const row = await fetchFeedbackRow(request, assistantMessageId)
          return Boolean((row.extra || {}).archived)
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBe(true)

      await page.getByRole('button', { name: '已归档' }).click()
      const archivedCard = page.locator('article').filter({ hasText: uniqueReason }).first()
      await expect(archivedCard).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(archivedCard.getByRole('button', { name: '取消归档' })).toBeVisible({
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
