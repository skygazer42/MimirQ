import fs from 'node:fs/promises'

import { expect, test, type APIRequestContext, type Download, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 300_000
const RULESET_NAME = 'industrial_control'
const REWRITE_QUERY = 'RS-485 授权报错怎么办'
const SUGGESTION_QUERY = 'PLC9 授权报错怎么办'

type IndustryRulesetSummary = {
  name?: string
  glossary_count?: number
  pattern_count?: number
  intent_count?: number
}

type IndustryRulesRewritePreviewResponse = {
  expanded_query?: string
  changed?: boolean
}

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

async function getObservabilitySettings(
  request: APIRequestContext
): Promise<LiveObservabilitySettings> {
  const response = await request.get(`${apiBaseUrl()}/api/v1/settings`, {
    headers: liveHeaders(),
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
      ...liveHeaders(),
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
    headers: liveHeaders(),
    data: {
      name,
      description: 'Playwright live industry-rules suggestion dataset.',
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
        retrieval_mode: 'hybrid',
        enable_reranker: false,
        enable_multi_query: false,
        enable_hyde: false,
        enable_query_decomposition: false,
        use_graph: false,
      },
    },
  })
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as LiveChatResponse
  const conversationId = String(body.conversation_id || '')
  expect(conversationId).toMatch(/\S/)
  return conversationId
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

async function fetchRuleSuggestions(
  request: APIRequestContext,
  datasetId: string
): Promise<Record<string, unknown>> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/datasets/${datasetId}/analysis/rule-suggestions?ruleset=${encodeURIComponent(RULESET_NAME)}&limit=20`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as Record<string, unknown>
}

async function waitForSuggestionToken(
  request: APIRequestContext,
  datasetId: string,
  token: string
): Promise<void> {
  await expect
    .poll(async () => {
      const payload = await fetchRuleSuggestions(request, datasetId)
      const suggestions = Array.isArray(payload.glossary_suggestions)
        ? payload.glossary_suggestions
        : []
      return suggestions.some(
        (row) => String((row as Record<string, unknown>).token || '').trim() === token
      )
    }, {
      timeout: LIVE_EXPECT_TIMEOUT_MS,
    })
    .toBe(true)
}

async function fetchIndustryRulesets(
  request: APIRequestContext
): Promise<IndustryRulesetSummary[]> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/industry-rules/rulesets`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { rulesets?: IndustryRulesetSummary[] }
  return Array.isArray(body.rulesets) ? body.rulesets : []
}

async function previewRewrite(
  request: APIRequestContext,
  query: string
): Promise<IndustryRulesRewritePreviewResponse> {
  const response = await request.post(
    `${apiBaseUrl()}/api/v1/industry-rules/preview-rewrite`,
    {
      headers: liveHeaders(),
      data: {
        ruleset: RULESET_NAME,
        query,
      },
    }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as IndustryRulesRewritePreviewResponse
}

async function readDownloadJson(download: Download): Promise<Record<string, unknown>> {
  const path = await download.path()
  expect(path).toBeTruthy()
  const content = await fs.readFile(String(path), 'utf8')
  return JSON.parse(content) as Record<string, unknown>
}

test.describe('live industry rules workbench', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('loads a real ruleset, proves rewrite preview, and exports the current ruleset on the deployed page host', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    try {
      const rulesets = await fetchIndustryRulesets(request)
      expect(
        rulesets.some((item) => String(item.name || '').trim() === RULESET_NAME)
      ).toBe(true)

      const rewrite = await previewRewrite(request, REWRITE_QUERY)
      expect(rewrite.changed).toBe(true)
      expect(String(rewrite.expanded_query || '')).toContain('RS-485 通讯线')

      await page.goto('/governance/industry-rules', { waitUntil: 'networkidle' })
      await expect(page.getByText('行业规则库')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.locator('#industry-rules-ruleset').click()
      await page.getByRole('option', { name: RULESET_NAME }).click()

      await page.locator('#industry-rules-preview-query').fill(REWRITE_QUERY)
      await expect(page.getByText('已命中规则并改写')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('RS-485 通讯线')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      const downloadPromise = page.waitForEvent('download')
      await page.getByRole('button', { name: '导出当前规则集' }).click()
      const download = await downloadPromise
      expect(download.suggestedFilename()).toBe(`${RULESET_NAME}.json`)
      const exported = await readDownloadJson(download)
      expect(String(exported.ruleset || '')).toBe(RULESET_NAME)
      expect(exported.glossary).toBeTruthy()

      expect(pageErrors).toEqual([])
    } finally {
      // No remote mutations in this proof path.
    }
  })

  test('refreshes real dataset-scoped glossary suggestions on the deployed page host', async ({
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

    const datasetName = `playwright-industry-rules-${Date.now()}`
    const filename = `industry-rules-${Date.now()}.md`
    const markdown = [
      '# Industry Rules Candidate Source',
      '',
      'PLC9 industrial control adapter appears in the troubleshooting notes.',
      '',
      'RS-485 通讯线 and PLC9 both appear in the same support document.',
      '',
      'The support team should recognize PLC9 as a glossary candidate when users ask about PLC9 faults.',
      '',
    ].join('\n')

    let datasetId = ''
    let conversationId = ''

    try {
      if (!originalMetricsEnabled) {
        await updateObservabilitySettings(request, {
          metrics_log_enabled: true,
          metrics_log_include_text: originalMetricsIncludeText,
        })
      }

      datasetId = await createLiveDataset(request, datasetName)
      const documentId = await uploadCompletedDocument(request, {
        datasetId,
        filename,
        content: markdown,
      })
      await waitForLiveDocumentStatus(request, documentId, 'completed')
      conversationId = await createLiveChat(request, {
        datasetId,
        message: SUGGESTION_QUERY,
      })

      await waitForSuggestionToken(request, datasetId, 'PLC9')

      await page.goto('/governance/industry-rules', { waitUntil: 'networkidle' })
      await expect(page.getByText('行业规则库')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.locator('#industry-rules-ruleset').click()
      await page.getByRole('option', { name: RULESET_NAME }).click()

      await page.locator('#industry-rules-dataset').click()
      await page.getByRole('option', { name: datasetName }).click()

      const candidatePanel = page
        .locator('div')
        .filter({ hasText: '规则候选（待审核）' })
        .first()
      await candidatePanel.getByRole('button', { name: '刷新' }).last().click()
      await expect(candidatePanel.getByText('PLC9')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(candidatePanel.getByText(`数据集 ${datasetName}`).first()).toBeVisible({
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
      if (!originalMetricsEnabled) {
        await updateObservabilitySettings(request, {
          metrics_log_enabled: originalMetricsEnabled,
          metrics_log_include_text: originalMetricsIncludeText,
        })
      }
    }
  })
})
