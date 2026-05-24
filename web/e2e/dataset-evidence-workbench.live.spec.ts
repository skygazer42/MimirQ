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

type EvidenceSuite = {
  id?: string
  name?: string
}

type EvidenceItem = {
  id?: string
  query?: string
  status?: string
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
      description: 'Playwright live dataset evidence workbench proof.',
      permission: 'all_team_members',
      default_parser_backend: 'basic',
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

async function retrieveEvidence(
  request: APIRequestContext,
  {
    datasetId,
    query,
  }: {
    datasetId: string
    query: string
  }
): Promise<{ citations?: Array<Record<string, unknown>>; has_evidence?: boolean }> {
  const response = await request.post(`${apiBaseUrl()}/api/v1/rag/retrieve`, {
    headers: {
      ...liveHeaders(),
      'Content-Type': 'application/json',
    },
    data: {
      query,
      history: [],
      dataset_id: datasetId,
      document_ids: [],
      rag_config: {
        retrieval_profile: 'recall50',
        max_tokens: 2000,
        retrieval_mode: 'hybrid',
        alpha: 0.6,
        enable_weight_rerank: true,
        vector_weight: 0.6,
        keyword_weight: 0.4,
        use_graph: false,
        visible_evidence_only: false,
      },
    },
  })
  expect(response.ok()).toBe(true)
  return (await response.json()) as {
    citations?: Array<Record<string, unknown>>
    has_evidence?: boolean
  }
}

async function listSuites(
  request: APIRequestContext,
  datasetId: string
): Promise<EvidenceSuite[]> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/evidence/suites?dataset_id=${encodeURIComponent(datasetId)}&include_archived=false&limit=200`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { items?: EvidenceSuite[] }
  return Array.isArray(body.items) ? body.items : []
}

async function listItems(
  request: APIRequestContext,
  suiteId: string
): Promise<EvidenceItem[]> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/evidence/suites/${encodeURIComponent(suiteId)}/items?limit=200`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { items?: EvidenceItem[] }
  return Array.isArray(body.items) ? body.items : []
}

async function createItem(
  request: APIRequestContext,
  {
    suiteId,
    datasetId,
    query,
    expectedAnswer,
    citation,
  }: {
    suiteId: string
    datasetId: string
    query: string
    expectedAnswer: string
    citation: Record<string, unknown>
  }
): Promise<EvidenceItem> {
  const response = await request.post(
    `${apiBaseUrl()}/api/v1/evidence/suites/${encodeURIComponent(suiteId)}/items`,
    {
      headers: {
        ...liveHeaders(),
        'Content-Type': 'application/json',
      },
      data: {
        suite_id: suiteId,
        dataset_id: datasetId,
        query,
        expected_answer: expectedAnswer,
        reference_sources: [
          {
            document_id: String(citation.document_id || ''),
            chunk_id: String(citation.chunk_id || ''),
            chunk_index:
              typeof citation.chunk_index === 'number'
                ? citation.chunk_index
                : null,
            page_number:
              typeof citation.page_number === 'number'
                ? citation.page_number
                : null,
            quote: String(citation.chunk_content || ''),
          },
        ],
        retrieval_snapshot: {
          created_from: 'retrieve',
        },
        rag_config_snapshot: {
          retrieval_profile: 'recall50',
        },
        notes: null,
      },
    }
  )
  expect(response.status()).toBe(201)
  return (await response.json()) as EvidenceItem
}

test.describe('live dataset evidence workbench page', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('creates a real Evidence Suite and shows a draft Evidence Item on the deployed page host', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const uniqueSuffix = `${Date.now()}`
    const datasetName = `playwright-evidence-suite-${uniqueSuffix}`
    const suiteName = `Playwright Evidence Suite ${uniqueSuffix}`
    const suiteDescription = 'Disposable suite created by the deployed evidence workbench proof.'
    const evidenceQuery = `Who owns token EVID-SUITE-${uniqueSuffix}?`
    const filename = `evidence-suite-${uniqueSuffix}.md`
    const markdown = [
      '# Evidence Suite Probe',
      '',
      `Token EVID-SUITE-${uniqueSuffix} belongs only to this document.`,
      'Owner: Eve Dence.',
    ].join('\n')

    let datasetId = ''

    try {
      datasetId = await createLiveDataset(request, datasetName)
      const documentId = await uploadCompletedDocument(request, {
        datasetId,
        filename,
        content: markdown,
      })
      await waitForLiveDocumentStatus(request, documentId, 'completed')

      const preflight = await retrieveEvidence(request, {
        datasetId,
        query: evidenceQuery,
      })
      expect(preflight.has_evidence).toBe(true)
      expect(Array.isArray(preflight.citations) && preflight.citations.length > 0).toBe(true)

      await page.goto(`/datasets/${encodeURIComponent(datasetId)}/evidence`, {
        waitUntil: 'networkidle',
      })
      await expect(
        page.getByRole('heading', { name: '证据库（Evidence Workbench）' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      const suitesPanel = page
        .locator('div')
        .filter({ hasText: 'Evidence Suites' })
        .filter({ hasText: '数据集：' })
        .first()
      await suitesPanel.getByRole('button', { name: '新建', exact: true }).first().click()
      const suiteDialog = page.getByRole('dialog')
      await expect(
        suiteDialog.getByRole('heading', { name: '新建 Evidence Suite' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await suiteDialog.locator('#suite-name').fill(suiteName)
      await suiteDialog.locator('#suite-desc').fill(suiteDescription)
      await suiteDialog.getByRole('button', { name: '创建' }).click()
      await expect(suiteDialog).toHaveCount(0, { timeout: LIVE_EXPECT_TIMEOUT_MS })

      let suiteId = ''
      await expect
        .poll(async () => {
          const suites = await listSuites(request, datasetId)
          const created = suites.find((suite) => String(suite.name || '') === suiteName)
          suiteId = String(created?.id || '')
          return suiteId
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toMatch(/\S/)

      await expect(
        page.getByRole('button', { name: new RegExp(suiteName) }).first()
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      const createdItem = await createItem(request, {
        suiteId,
        datasetId,
        query: evidenceQuery,
        expectedAnswer: 'Eve Dence',
        citation: preflight.citations?.[0] || {},
      })
      expect(String(createdItem.status || '')).toBe('draft')

      await page.getByRole('button', { name: '刷新 Items' }).click()

      await expect
        .poll(async () => {
          const items = await listItems(request, suiteId)
          return items.some(
            (item) =>
              String(item.query || '') === evidenceQuery &&
              String(item.status || '') === 'draft'
          )
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBe(true)

      await expect(page.getByText(evidenceQuery)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(
        page.getByRole('button', { name: new RegExp(evidenceQuery) }).first()
      ).toContainText('draft', {
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      expect(pageErrors).toEqual([])
    } finally {
      if (datasetId) {
        await deleteLiveDataset(request, datasetId)
      }
    }
  })
})
