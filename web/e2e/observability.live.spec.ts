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
}

type LiveObservabilitySettings = {
  metrics_log_enabled?: boolean
  metrics_log_include_text?: boolean
}

type LiveMetricsSummary = {
  enabled?: boolean
  rag_trace_count?: number
}

type LiveQueryAnalytics = {
  enabled?: boolean
  rag_trace_count?: number
  unique_query_hashes?: number
  zero_hit_count?: number
  top_zero_hit_queries?: Array<{ query_hash?: string; count?: number }>
}

function apiBaseUrl(): string {
  return String(
    process.env.PLAYWRIGHT_LIVE_API_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      'http://127.0.0.1:8000'
  ).replace(/\/+$/, '')
}

function liveHeaders() {
  return {
    tenantId:
      process.env.PLAYWRIGHT_LIVE_TENANT_ID ||
      process.env.NEXT_PUBLIC_TENANT_ID ||
      DEFAULT_TENANT_ID,
    userId:
      process.env.PLAYWRIGHT_LIVE_USER_ID ||
      process.env.NEXT_PUBLIC_USER_ID ||
      DEFAULT_USER_ID,
  }
}

function liveApiHeaders(): Record<string, string> {
  const auth = liveHeaders()
  return {
    'X-Tenant-ID': auth.tenantId,
    'X-Account-ID': auth.userId,
    'X-User-ID': auth.userId,
  }
}

async function installLiveAuth(page: Page) {
  const headers = liveHeaders()
  await page.addInitScript(
    ({ tenantId, userId }) => {
      window.localStorage.setItem('mimirq_tenant_id', tenantId)
      window.localStorage.setItem('mimirq_user_id', userId)
    },
    headers
  )
}

async function assertResultPanel(
  page: Page,
  {
    title,
    expectedTexts,
  }: {
    title: string
    expectedTexts: string[]
  }
) {
  await expect(page.getByText(title, { exact: true })).toBeVisible({
    timeout: LIVE_EXPECT_TIMEOUT_MS,
  })
  await page.getByText('查看原始响应', { exact: true }).click()
  const rawPanel = page.locator('details pre').last()
  for (const text of expectedTexts) {
    await expect(rawPanel).toContainText(text, {
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })
  }
}

function shortHash(value: string, opts?: { head?: number; tail?: number }) {
  const v = String(value || '').trim()
  if (!v) return ''
  const head = Math.max(1, Number(opts?.head ?? 8) || 8)
  const tail = Math.max(0, Number(opts?.tail ?? 4) || 4)
  if (v.length <= head + tail + 1) return v
  return `${v.slice(0, head)}...${v.slice(-tail)}`
}

async function getObservabilitySettings(
  request: APIRequestContext
): Promise<LiveObservabilitySettings> {
  const response = await request.get(`${apiBaseUrl()}/api/v1/settings`, {
    headers: liveApiHeaders(),
  })
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as {
    observability?: LiveObservabilitySettings
  }
  return body.observability || {}
}

async function updateObservabilitySettings(
  request: APIRequestContext,
  payload: LiveObservabilitySettings
): Promise<void> {
  const response = await request.put(`${apiBaseUrl()}/api/v1/settings`, {
    headers: {
      ...liveApiHeaders(),
      'Content-Type': 'application/json',
    },
    data: {
      observability: payload,
    },
  })
  expect(response.ok()).toBe(true)
}

async function createLiveDataset(
  request: APIRequestContext,
  name: string
): Promise<string> {
  const response = await request.post(`${apiBaseUrl()}/api/v1/datasets/`, {
    headers: liveApiHeaders(),
    data: {
      name,
      description: 'Playwright live observability metrics dataset.',
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
      headers: liveApiHeaders(),
      data: {},
    }
  )
  expect(purgeResponse.ok()).toBe(true)

  const response = await request.delete(
    `${apiBaseUrl()}/api/v1/datasets/${datasetId}`,
    { headers: liveApiHeaders() }
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
    headers: liveApiHeaders(),
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
    { headers: liveApiHeaders() }
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
    retrievalMode = 'hybrid',
    scoreThreshold = 0.0,
  }: {
    datasetId: string
    message: string
    retrievalMode?: 'hybrid' | 'keyword' | 'vector'
    scoreThreshold?: number
  }
): Promise<LiveChatResponse> {
  const response = await request.post(`${apiBaseUrl()}/api/v1/chat`, {
    headers: {
      ...liveApiHeaders(),
      'Content-Type': 'application/json',
    },
    data: {
      message,
      dataset_id: datasetId,
      stream: false,
      rag_config: {
        top_k: 4,
        score_threshold: scoreThreshold,
        retrieval_mode: retrievalMode,
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
  return body
}

async function deleteConversation(
  request: APIRequestContext,
  conversationId: string
): Promise<void> {
  const response = await request.delete(
    `${apiBaseUrl()}/api/v1/chat/conversations/${conversationId}`,
    { headers: liveApiHeaders() }
  )
  expect([200, 204]).toContain(response.status())
}

async function fetchMetricsSummary(
  request: APIRequestContext,
  windowMinutes = 60
): Promise<LiveMetricsSummary> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/observability/rag-metrics/summary?window_minutes=${windowMinutes}`,
    { headers: liveApiHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as LiveMetricsSummary
}

async function fetchQueryAnalytics(
  request: APIRequestContext,
  windowMinutes = 60,
  slowThresholdSec = 2
): Promise<LiveQueryAnalytics> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/observability/rag-metrics/query-analytics?window_minutes=${windowMinutes}&slow_threshold_sec=${slowThresholdSec}`,
    { headers: liveApiHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as LiveQueryAnalytics
}

async function assertStatCardValue(
  page: Page,
  label: string,
  value: string
): Promise<void> {
  const labelNode = page.getByText(label, { exact: true }).first()
  await expect(labelNode).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
  const card = labelNode.locator(
    'xpath=ancestor::div[contains(@class,"rounded-2xl") or contains(@class,"rounded-xl")][1]'
  )
  await expect(card).toContainText(value, { timeout: LIVE_EXPECT_TIMEOUT_MS })
}

test.describe('live observability workbench', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('runs real observability ops actions on the deployed page host', async ({
    page,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    await page.goto('/observability', { waitUntil: 'networkidle' })
    await expect(
      page.getByRole('heading', { name: '监控面板' })
    ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
    await expect(page.getByText('观测运维操作')).toBeVisible({
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })

    await page.getByRole('button', { name: '依赖健康' }).click()
    await assertResultPanel(page, {
      title: '依赖诊断快照',
      expectedTexts: [
        'mimirq.observability.deps.v1',
        '"postgres"',
        '"redis"',
      ],
    })

    await page.getByRole('button', { name: '任务队列' }).click()
    await assertResultPanel(page, {
      title: '任务队列快照',
      expectedTexts: [
        'mimirq.task_queue_observability.v1',
        '"queue_depth"',
        '"workers_active"',
      ],
    })

    await page.getByRole('button', { name: 'SLO' }).click()
    await assertResultPanel(page, {
      title: 'SLO 快照',
      expectedTexts: [
        'mimirq.slo_snapshot.v1',
        '"window_minutes": 60',
        '"window_minutes": 1440',
      ],
    })

    await page.getByText('高级参数（可选）').click()
    await page.getByRole('button', { name: 'Trace 上报' }).click()
    await assertResultPanel(page, {
      title: '前端 Trace 上报',
      expectedTexts: ['"reported": true', 'manual_observability_probe'],
    })

    expect(pageErrors).toEqual([])
  })

  test('shows live metrics summary and query analytics after enabling metrics logging and seeding extractive chats', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const originalObservability = await getObservabilitySettings(request)
    const originalMetricsEnabled = Boolean(originalObservability.metrics_log_enabled)
    const originalMetricsIncludeText = Boolean(
      originalObservability.metrics_log_include_text
    )

    const datasetName = `playwright-observability-${Date.now()}`
    const zeroHitQuery = 'qwertyuiop asdfghjkl zxcvbnm'
    const groundedQuery = 'What token belongs only to OBS?'

    let datasetId = ''
    const conversationIds: string[] = []

    try {
      if (!originalMetricsEnabled) {
        await updateObservabilitySettings(request, {
          metrics_log_enabled: true,
          metrics_log_include_text: originalMetricsIncludeText,
        })
        await expect
          .poll(async () => {
            const current = await getObservabilitySettings(request)
            return Boolean(current.metrics_log_enabled)
          }, {
            timeout: LIVE_EXPECT_TIMEOUT_MS,
          })
          .toBe(true)
      }

      const baselineSummary = await fetchMetricsSummary(request)
      const baselineAnalytics = await fetchQueryAnalytics(request)

      datasetId = await createLiveDataset(request, datasetName)
      const documentId = await uploadCompletedDocument(request, {
        datasetId,
        filename: `observability-${Date.now()}.md`,
        content: [
          '# Observability Metrics',
          '',
          'Token OBS belongs only here.',
          '',
          'This document exists only to exercise extractive metrics logging.',
          '',
        ].join('\n'),
      })
      await waitForLiveDocumentStatus(request, documentId, 'completed')

      const groundedChat = await createLiveChat(request, {
        datasetId,
        message: groundedQuery,
      })
      conversationIds.push(String(groundedChat.conversation_id || ''))

      const zeroHitChat = await createLiveChat(request, {
        datasetId,
        message: zeroHitQuery,
        retrievalMode: 'keyword',
        scoreThreshold: 1.0,
      })
      conversationIds.push(String(zeroHitChat.conversation_id || ''))

      let summaryAfter: LiveMetricsSummary = {}
      let analyticsAfter: LiveQueryAnalytics = {}
      await expect
        .poll(async () => {
          summaryAfter = await fetchMetricsSummary(request)
          analyticsAfter = await fetchQueryAnalytics(request)
          const summaryCount = Number(summaryAfter.rag_trace_count || 0)
          const analyticsCount = Number(analyticsAfter.rag_trace_count || 0)
          const zeroHitCount = Number(analyticsAfter.zero_hit_count || 0)
          const topZeroHit =
            (analyticsAfter.top_zero_hit_queries || []).find(
              (item) => Number(item.count || 0) >= 1
            ) || null
          return (
            Boolean(summaryAfter.enabled) &&
            Boolean(analyticsAfter.enabled) &&
            summaryCount >= Number(baselineSummary.rag_trace_count || 0) + 1 &&
            analyticsCount >= Number(baselineAnalytics.rag_trace_count || 0) + 1 &&
            zeroHitCount >= Number(baselineAnalytics.zero_hit_count || 0) + 1 &&
            Boolean(topZeroHit?.query_hash)
          )
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBe(true)

      const zeroHitEntry =
        (analyticsAfter.top_zero_hit_queries || []).find(
          (item) => Number(item.count || 0) >= 1
        ) || null
      expect(zeroHitEntry?.query_hash).toBeTruthy()
      const displayedZeroHitHash = shortHash(String(zeroHitEntry?.query_hash || ''), {
        head: 10,
        tail: 6,
      })

      await page.goto('/observability', { waitUntil: 'networkidle' })
      await expect(
        page.getByRole('heading', { name: '监控面板' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await expect(
        page.getByText('Metrics 日志未开启', { exact: true })
      ).toHaveCount(0)

      await page.getByRole('button', { name: '刷新' }).click()
      await assertStatCardValue(
        page,
        'RAG Trace',
        String(Number(summaryAfter.rag_trace_count || 0))
      )

      await page.getByRole('tab', { name: 'Query Analytics' }).click()
      await page.getByRole('button', { name: '刷新' }).click()
      await expect(
        page.getByText(
          '当前 ENABLE_METRICS_LOG=false。Query Analytics 只基于 rag_trace 指标聚合。'
        )
      ).toHaveCount(0)
      await assertStatCardValue(
        page,
        'Requests',
        String(Number(analyticsAfter.rag_trace_count || 0))
      )
      await assertStatCardValue(
        page,
        'Unique query_hash',
        String(Number(analyticsAfter.unique_query_hashes || 0))
      )
      await expect(page.getByText(displayedZeroHitHash, { exact: true })).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      expect(pageErrors).toEqual([])
    } finally {
      for (const conversationId of conversationIds) {
        if (!conversationId) continue
        await deleteConversation(request, conversationId)
      }
      if (datasetId) {
        await deleteLiveDataset(request, datasetId)
      }
      if (!originalMetricsEnabled) {
        await updateObservabilitySettings(request, {
          metrics_log_enabled: originalMetricsEnabled,
          metrics_log_include_text: originalMetricsIncludeText,
        })
      }
    }
  })
})
