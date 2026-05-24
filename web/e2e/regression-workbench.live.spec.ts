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
      description: 'Playwright live regression workbench dataset.',
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
        tags: ['golden', 'playwright', 'regression-live'],
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

async function listRegressionRuns(
  request: APIRequestContext,
  datasetId: string
): Promise<Array<{ id?: string }>> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/evaluations/ragas/regression/runs?limit=50&dataset_id=${encodeURIComponent(datasetId)}`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as {
    items?: Array<{ id?: string }>
  }
  return Array.isArray(body.items) ? body.items : []
}

test.describe('live regression workbench', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('shows a real golden case and creates a real regression run on the deployed page host', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const datasetName = `playwright-regression-${Date.now()}`
    const filename = `regression-${Date.now()}.md`
    const question = 'Who owns token REG-ANCHOR?'
    const expectedAnswer = 'Rina Anchor'
    const markdown = [
      '# Regression Probe',
      '',
      'Token REG-ANCHOR belongs only to this document.',
      'Owner: Rina Anchor.',
      '',
    ].join('\n')

    let datasetId = ''
    let regressionCaseId = ''

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

      regressionCaseId = await createGoldenRegressionCase(request, {
        datasetId,
        documentId,
        chunkId,
        question,
        expectedAnswer,
      })

      const beforeRuns = await listRegressionRuns(request, datasetId)
      const beforeCount = beforeRuns.length

      await page.goto('/evaluations?tab=regression', { waitUntil: 'networkidle' })
      await expect(
        page.getByRole('heading', { name: 'Golden 评测集' })
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      const datasetCombo = page.getByRole('combobox').filter({ hasText: /选择数据集|playwright-regression-/ }).first()
      await datasetCombo.click()
      await page.getByRole('option', { name: datasetName }).click()

      await expect(page.getByText(question)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('Golden 1')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.getByRole('button', { name: '运行 Golden' }).click()
      await expect(page.getByText('开始运行 Golden 评测')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      let latestRunId = ''
      await expect
        .poll(async () => {
          const runs = await listRegressionRuns(request, datasetId)
          latestRunId = String(runs[0]?.id || '')
          return runs.length
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBeGreaterThan(beforeCount)

      const runIdShort = latestRunId.slice(0, 8)
      expect(runIdShort).toMatch(/\S/)
      await expect(page.getByText(`运行 ${runIdShort}`)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      expect(pageErrors).toEqual([])
    } finally {
      if (regressionCaseId) {
        await deleteRegressionCase(request, regressionCaseId)
      }
      if (datasetId) {
        await deleteLiveDataset(request, datasetId)
      }
    }
  })
})
