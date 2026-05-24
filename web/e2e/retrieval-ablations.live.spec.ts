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

type LiveChunkList = {
  items?: Array<{ id?: string }>
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
      description: 'Playwright live retrieval ablations dataset.',
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

async function listChunks(
  request: APIRequestContext,
  documentId: string
): Promise<LiveChunkList> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/documents/${documentId}/chunks?limit=20`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as LiveChunkList
}

async function createGoldenRegressionCase(
  request: APIRequestContext,
  {
    datasetId,
    documentId,
    chunkId,
    question,
    expectedAnswer,
  }: {
    datasetId: string
    documentId: string
    chunkId: string
    question: string
    expectedAnswer: string
  }
): Promise<string> {
  const response = await request.post(
    `${apiBaseUrl()}/api/v1/evaluations/ragas/regression/cases`,
    {
      headers: {
        ...liveHeaders(),
        'Content-Type': 'application/json',
      },
      data: {
        question,
        dataset_id: datasetId,
        document_ids: [],
        expected_answer: expectedAnswer,
        reference_sources: [
          {
            document_id: documentId,
            chunk_id: chunkId,
          },
        ],
        tags: ['golden', 'playwright', 'ablation-live'],
      },
    }
  )
  expect(response.status()).toBe(201)
  const body = (await response.json()) as { id?: string }
  const caseId = String(body.id || '')
  expect(caseId).toMatch(/\S/)
  return caseId
}

async function deleteRegressionCase(
  request: APIRequestContext,
  caseId: string
): Promise<void> {
  const response = await request.delete(
    `${apiBaseUrl()}/api/v1/evaluations/ragas/regression/cases/${caseId}`,
    { headers: liveHeaders() }
  )
  expect([200, 204]).toContain(response.status())
}

async function createRegressionRun(
  request: APIRequestContext,
  payload: Record<string, unknown>
): Promise<string> {
  const response = await request.post(
    `${apiBaseUrl()}/api/v1/evaluations/ragas/regression/runs`,
    {
      headers: {
        ...liveHeaders(),
        'Content-Type': 'application/json',
      },
      data: payload,
    }
  )
  expect(response.status()).toBe(201)
  const body = (await response.json()) as { id?: string }
  const runId = String(body.id || '')
  expect(runId).toMatch(/\S/)
  return runId
}

async function waitForRegressionRunStatus(
  request: APIRequestContext,
  runId: string,
  expectedStatus: string
): Promise<void> {
  await expect
    .poll(async () => {
      const response = await request.get(
        `${apiBaseUrl()}/api/v1/evaluations/ragas/regression/runs/${runId}?include_items=true&include_contexts=false`,
        { headers: liveHeaders() }
      )
      expect(response.ok()).toBe(true)
      const body = (await response.json()) as {
        run?: { status?: string }
      }
      return String(body.run?.status || '').toLowerCase()
    }, {
      timeout: 180_000,
    })
    .toBe(expectedStatus)
}

test.describe('live retrieval ablations workbench', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('loads two real runs and generates a diff on the deployed page host', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const datasetName = `playwright-ablations-${Date.now()}`
    const filename = `ablations-${Date.now()}.md`
    const question = 'Who owns token ABL-ANCHOR?'
    const expectedAnswer = 'Ari Blend'
    const markdown = [
      '# Ablation Probe',
      '',
      'Token ABL-ANCHOR belongs only to this document.',
      'Owner: Ari Blend.',
      '',
    ].join('\n')

    let datasetId = ''
    let caseId = ''

    try {
      datasetId = await createLiveDataset(request, datasetName)
      const documentId = await uploadCompletedDocument(request, {
        datasetId,
        filename,
        content: markdown,
      })
      await waitForLiveDocumentStatus(request, documentId, 'completed')
      const chunks = await listChunks(request, documentId)
      const chunkId = String(chunks.items?.[0]?.id || '')
      expect(chunkId).toMatch(/\S/)

      caseId = await createGoldenRegressionCase(request, {
        datasetId,
        documentId,
        chunkId,
        question,
        expectedAnswer,
      })

      const basePayload = {
        case_ids: [caseId],
        dataset_id: datasetId,
        metrics: [],
        skip_empty_contexts: true,
        max_cases: 1,
        top_k: 20,
        score_threshold: 0.0,
        retrieval_mode: 'keyword',
        alpha: 0.6,
        enable_weight_rerank: true,
        vector_weight: 0.6,
        keyword_weight: 0.4,
        mmr_lambda: 0.7,
        enable_reranker: false,
        reranker_provider: 'llm',
        reranker_top_n: 20,
      }
      const targetPayload = {
        ...basePayload,
        retrieval_mode: 'hybrid',
      }

      const baseRunId = await createRegressionRun(request, basePayload)
      const targetRunId = await createRegressionRun(request, targetPayload)
      await waitForRegressionRunStatus(request, baseRunId, 'completed')
      await waitForRegressionRunStatus(request, targetRunId, 'completed')

      await page.goto('/evaluations/ablations', { waitUntil: 'networkidle' })
      await expect(
        page.getByRole('heading', { name: '检索消融实验' })
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.getByLabel('当前数据集').click()
      await page.getByRole('option', { name: datasetName }).click()

      await page.getByRole('button', { name: '生成对比' }).click()
      await expect(page.getByText('已生成差异对比')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.getByRole('tab', { name: '原始数据' }).click()
      const rawPane = page.locator('text=对比数据').locator('..').locator('..')
      await expect(rawPane).toContainText(baseRunId, {
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(rawPane).toContainText(targetRunId, {
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(rawPane).toContainText('"metric_diffs"', {
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      expect(pageErrors).toEqual([])
    } finally {
      if (caseId) {
        await deleteRegressionCase(request, caseId)
      }
      if (datasetId) {
        await deleteLiveDataset(request, datasetId)
      }
    }
  })
})
