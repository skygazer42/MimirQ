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

type GovernanceProfileOut = {
  id?: string
  key?: string
  name?: string
  payload?: {
    regex_rules?: Array<{
      pattern?: string
      repl?: string
      flags?: number
    }>
  }
}

type GovernanceCommonLinesCandidate = {
  signature?: string
  sample?: string
  docs?: number
  ratio?: number
}

type GovernanceCommonLinesLearnResponse = {
  dataset_id?: string
  total_documents?: number
  used_documents?: number
  candidates?: GovernanceCommonLinesCandidate[]
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

function escapeRegex(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function buildLineRegexPattern(sample: string): string {
  const raw = String(sample || '').trim()
  const tokens = raw.split(/\s+/).filter(Boolean)
  return String.raw`(?mi)^\s*${tokens.map(escapeRegex).join(String.raw`\s+`)}\s*$`
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
      description: 'Playwright live common-lines dataset.',
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

async function createProfile(
  request: APIRequestContext,
  {
    name,
    key,
    description,
  }: {
    name: string
    key: string
    description: string
  }
): Promise<GovernanceProfileOut> {
  const response = await request.post(
    `${apiBaseUrl()}/api/v1/pipeline/governance-profiles`,
    {
      headers: {
        ...liveHeaders(),
        'Content-Type': 'application/json',
      },
      data: {
        name,
        key,
        description,
        payload: {
          version: '1',
          input_formats: ['markdown'],
          pipeline_patch: {
            governance_enabled: true,
            governance_remove_toc_lines: true,
            governance_remove_noise_lines: true,
            governance_unwrap_lines: true,
            governance_remove_common_lines: true,
            governance_max_blank_lines: 1,
          },
          regex_rules: [],
        },
      },
    }
  )
  expect(response.status()).toBe(201)
  return (await response.json()) as GovernanceProfileOut
}

async function getProfile(
  request: APIRequestContext,
  profileRef: string
): Promise<GovernanceProfileOut> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/pipeline/governance-profiles/${encodeURIComponent(profileRef)}`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as GovernanceProfileOut
}

async function deleteProfileByRef(
  request: APIRequestContext,
  profileRef: string
): Promise<void> {
  const response = await request.delete(
    `${apiBaseUrl()}/api/v1/pipeline/governance-profiles/${encodeURIComponent(profileRef)}`,
    { headers: liveHeaders() }
  )
  expect([200, 204]).toContain(response.status())
}

async function learnCommonLines(
  request: APIRequestContext,
  {
    datasetId,
    minDocs,
  }: {
    datasetId: string
    minDocs: number
  }
): Promise<GovernanceCommonLinesLearnResponse> {
  const response = await request.post(
    `${apiBaseUrl()}/api/v1/pipeline/learn-common-lines`,
    {
      headers: {
        ...liveHeaders(),
        'Content-Type': 'application/json',
      },
      data: {
        dataset_id: datasetId,
        limit_docs: 10,
        use_original: true,
        min_docs: minDocs,
        min_ratio: 1.0,
        max_line_length: 200,
        max_candidates: 20,
      },
    }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as GovernanceCommonLinesLearnResponse
}

test.describe('live governance common-lines workbench', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('learns common lines from a real dataset and writes rules into a real governance profile', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const uniqueSuffix = `${Date.now()}`
    const repeatedLine = `COMMON-LINES-ANCHOR-${uniqueSuffix} Shared Header`
    const datasetName = `playwright-common-lines-${uniqueSuffix}`
    const profileName = `Playwright Common Lines ${uniqueSuffix}`
    const profileKey = `playwright-common-lines-${uniqueSuffix}`
    const profileDescription =
      'Disposable governance profile for common-lines live proof.'

    let datasetId = ''
    let profileRef = ''

    try {
      datasetId = await createLiveDataset(request, datasetName)
      const createdProfile = await createProfile(request, {
        name: profileName,
        key: profileKey,
        description: profileDescription,
      })
      profileRef =
        String(createdProfile.id || '').trim() ||
        String(createdProfile.key || '').trim()
      expect(profileRef).toMatch(/\S/)

      const documents = [
        {
          filename: `common-lines-a-${uniqueSuffix}.md`,
          content: [
            repeatedLine,
            '',
            '# Alpha Note',
            '',
            'Unique payload A.',
            'Owner: Alice Header.',
          ].join('\n'),
        },
        {
          filename: `common-lines-b-${uniqueSuffix}.md`,
          content: [
            repeatedLine,
            '',
            '# Beta Note',
            '',
            'Unique payload B.',
            'Owner: Bob Header.',
          ].join('\n'),
        },
        {
          filename: `common-lines-c-${uniqueSuffix}.md`,
          content: [
            repeatedLine,
            '',
            '# Gamma Note',
            '',
            'Unique payload C.',
            'Owner: Carol Header.',
          ].join('\n'),
        },
      ]

      const documentIds = await Promise.all(
        documents.map(({ filename, content }) =>
          uploadCompletedDocument(request, {
            datasetId,
            filename,
            content,
          })
        )
      )
      await Promise.all(
        documentIds.map((documentId) =>
          waitForLiveDocumentStatus(request, documentId, 'completed')
        )
      )

      const preflight = await learnCommonLines(request, {
        datasetId,
        minDocs: documents.length,
      })
      expect(preflight.dataset_id).toBe(datasetId)
      expect(preflight.used_documents).toBe(documents.length)
      const expectedCandidate = (preflight.candidates || []).find((candidate) =>
        `${candidate.sample || ''} ${candidate.signature || ''}`
          .toLowerCase()
          .includes(uniqueSuffix.toLowerCase())
      )
      expect(expectedCandidate).toBeTruthy()
      expect(expectedCandidate?.docs).toBe(documents.length)

      await page.goto('/data-governance/common-lines', {
        waitUntil: 'networkidle',
      })
      await expect(
        page.getByRole('heading', { name: '重复行学习' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      const comboboxes = page.getByRole('combobox')
      await comboboxes.nth(0).click()
      await page.getByRole('option', { name: datasetName }).click()

      await comboboxes.nth(1).click()
      await page.getByRole('option', { name: profileName }).click()

      await page.getByRole('button', { name: '扫描' }).click()

      await expect(page.locator(`[title="${repeatedLine}"]`).first()).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText(`扫描 ${documents.length}/${documents.length} 文档`)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('共 1')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.getByRole('checkbox').last().click()
      await expect(page.getByRole('button', { name: '写入配置 (1)' })).toBeEnabled({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.getByRole('button', { name: '写入配置 (1)' }).click()
      await page.waitForURL(/\/data-governance\/profiles/, {
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(
        page.getByRole('heading', { name: '治理配置' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      const profile = await getProfile(request, profileRef)
      const patterns = (profile.payload?.regex_rules || []).map((rule) =>
        String(rule.pattern || '')
      )
      expect(patterns).toContain(buildLineRegexPattern(repeatedLine))

      expect(pageErrors).toEqual([])
    } finally {
      if (profileRef) {
        await deleteProfileByRef(request, profileRef)
      }
      if (datasetId) {
        await deleteLiveDataset(request, datasetId)
      }
    }
  })
})
