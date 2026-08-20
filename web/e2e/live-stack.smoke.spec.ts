import path from 'node:path'

import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const FIXTURE_PATH = path.resolve(__dirname, 'fixtures/live-browser-smoke.txt')
const FIXTURE_FILENAME = path.basename(FIXTURE_PATH)
const FIXTURE_TOKEN = 'LIVE-CLOSED-LOOP-AXIOM-2049'
const DEFAULT_HEADER_USER_ID = 'demo'
const DEFAULT_HEADER_TENANT_ID = '00000000-0000-0000-0000-000000000000'

type AuthMode = 'jwt' | 'header'

type HeaderAuthState = {
  mode: 'header'
  userId: string
  tenantId: string
}

type JwtAuthState = {
  mode: 'jwt'
  accessToken: string
}

type AuthState = HeaderAuthState | JwtAuthState

function uniqueSuffix() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function resolveHeaderUserId() {
  return (process.env.PLAYWRIGHT_LIVE_USER_ID || process.env.NEXT_PUBLIC_USER_ID || DEFAULT_HEADER_USER_ID).trim()
}

function resolveHeaderTenantId() {
  const rawTenantId = (
    process.env.PLAYWRIGHT_LIVE_TENANT_ID ||
    process.env.NEXT_PUBLIC_TENANT_ID ||
    DEFAULT_HEADER_TENANT_ID
  ).trim()
  return rawTenantId.toLowerCase() === 'zero' ? DEFAULT_HEADER_TENANT_ID : rawTenantId
}

function authHeaders(auth: AuthState): Record<string, string> {
  if (auth.mode === 'jwt') {
    return {
      Authorization: `Bearer ${auth.accessToken}`,
      Accept: 'application/json',
    }
  }

  return {
    'X-User-ID': auth.userId,
    'X-Tenant-ID': auth.tenantId,
    Accept: 'application/json',
  }
}

async function detectAuthMode(request: APIRequestContext): Promise<AuthMode> {
  const response = await request.get('/api/v1/meta', {
    headers: { Accept: 'application/json' },
  })
  expect(response.ok()).toBeTruthy()
  const payload = (await response.json()) as {
    features?: {
      auth_mode?: string
    }
  }
  const authMode = String(payload.features?.auth_mode || 'jwt').trim().toLowerCase()
  return authMode === 'header' ? 'header' : 'jwt'
}

async function expectHealthEndpoints(page: Page) {
  await expect
    .poll(
      async () =>
        page.evaluate(async () => {
          const paths = ['/api/v1/health', '/api/v1/health/ready', '/api/v1/meta']
          return Promise.all(
            paths.map(async (probePath) => {
              const response = await fetch(probePath, { headers: { Accept: 'application/json' } })
              return {
                path: probePath,
                status: response.status,
                contentType: response.headers.get('content-type') || '',
              }
            })
          )
        }),
      {
        timeout: 180_000,
        intervals: [1_000, 2_000, 5_000],
        message: 'expected proxied health endpoints to become ready',
      }
    )
    .toEqual([
      expect.objectContaining({ path: '/api/v1/health', status: 200, contentType: expect.stringContaining('json') }),
      expect.objectContaining({
        path: '/api/v1/health/ready',
        status: 200,
        contentType: expect.stringContaining('json'),
      }),
      expect.objectContaining({ path: '/api/v1/meta', status: 200, contentType: expect.stringContaining('json') }),
    ])
}

async function selectFullIndexExecutionMode(page: Page) {
  const executionField = page.getByText('执行阶段', { exact: true }).locator('..')
  const executionMode = executionField.getByRole('combobox')
  await expect(executionMode).toBeVisible({ timeout: 60_000 })
  await executionMode.click()
  await page.getByRole('option', { name: /解析 \+ 索引/ }).click()
  await expect(executionMode).toContainText('解析 + 索引')
}

async function selectChatDatasetScope(page: Page, datasetName: string) {
  const scopeTrigger = page.getByRole('button', { name: '选择数据集', exact: true })
  if (!(await scopeTrigger.isVisible())) {
    const toolsTrigger = page.locator('button[aria-controls="chat-conversation-tools"]')
    await expect(toolsTrigger).toBeVisible({ timeout: 60_000 })
    await toolsTrigger.click()
  }
  await expect(scopeTrigger).toBeVisible({ timeout: 60_000 })
  await scopeTrigger.click()
  await page.getByRole('button', { name: new RegExp(datasetName) }).last().click()
  await expect(scopeTrigger).toContainText(datasetName)
}

async function readAccessToken(page: Page) {
  const accessToken = await page.evaluate(() => {
    return (
      window.sessionStorage.getItem('mimirq_access_token') ||
      window.localStorage.getItem('mimirq_access_token') ||
      ''
    )
  })
  expect(accessToken).toBeTruthy()
  return accessToken
}

async function authenticateThroughUi(page: Page): Promise<JwtAuthState> {
  const configuredIdentifier = (process.env.PLAYWRIGHT_LIVE_IDENTIFIER || '').trim()
  const configuredPassword = (process.env.PLAYWRIGHT_LIVE_PASSWORD || '').trim()

  if (!configuredIdentifier || !configuredPassword) {
    throw new Error(
      'JWT live smoke requires PLAYWRIGHT_LIVE_IDENTIFIER and PLAYWRIGHT_LIVE_PASSWORD; refusing to bootstrap a persistent administrator'
    )
  }

  await page.goto('/auth')
  await expect(page.getByLabel('账号')).toBeVisible()
  await expect(page.getByLabel('密码')).toBeVisible()

  await page.getByLabel('账号').fill(configuredIdentifier)
  await page.getByLabel('密码').fill(configuredPassword)
  await page.locator('form').getByRole('button', { name: '登 录', exact: true }).click()
  await page.waitForURL(/\/$/, { timeout: 60_000 })
  return { mode: 'jwt', accessToken: await readAccessToken(page) }
}

async function createDataset(request: APIRequestContext, page: Page, auth: AuthState) {
  const datasetName = `playwright-live-${uniqueSuffix()}`
  const response = await request.post('/api/v1/datasets/', {
    headers: authHeaders(auth),
    data: {
      name: datasetName,
      description: 'Live browser closed-loop smoke dataset',
    },
  })
  expect(response.ok()).toBeTruthy()
  const payload = await response.json()
  expect(payload.id).toBeTruthy()

  await page.reload()
  return {
    id: String(payload.id),
    name: String(payload.name || datasetName),
  }
}

async function waitForDocumentCompletion(
  request: APIRequestContext,
  auth: AuthState,
  documentId: string
) {
  const deadline = Date.now() + 180_000
  let lastStatus = ''
  let lastBody = ''

  while (Date.now() < deadline) {
    const response = await request.get(`/api/v1/documents/${documentId}/status`, {
      headers: authHeaders(auth),
    })
    lastBody = await response.text()
    if (!response.ok()) {
      throw new Error(
        `document status request failed for ${documentId}: http_status=${response.status()} body=${lastBody}`
      )
    }
    const payload = JSON.parse(lastBody) as { status?: string }
    const status = String(payload.status || '')
    lastStatus = status
    if (status === 'completed') return
    if (['failed', 'quarantined', 'cancelled', 'deleting'].includes(status)) {
      throw new Error(`document ${documentId} entered terminal status=${status}; body=${lastBody}`)
    }

    await new Promise((resolve) => setTimeout(resolve, 2_000))
  }

  throw new Error(`timed out waiting for ${documentId} to complete; last_status=${lastStatus}; last_body=${lastBody}`)
}

async function cleanupDataset(request: APIRequestContext, auth: AuthState | null, datasetId: string | null) {
  if (!datasetId) return
  if (!auth) return

  const purge = await request.post(`/api/v1/datasets/${datasetId}/purge`, {
    headers: authHeaders(auth),
    params: {
      dry_run: 'false',
      max_delete: '100',
    },
    data: {},
  })
  expect([200, 204]).toContain(purge.status())

  const remove = await request.delete(`/api/v1/datasets/${datasetId}`, {
    headers: authHeaders(auth),
  })
  expect([204, 404]).toContain(remove.status())
}

test('browser reaches the live backend and completes upload-to-grounded-chat evidence loop', async ({
  page,
  request,
}) => {
  test.setTimeout(600_000)
  let auth: AuthState | null = null
  let datasetId: string | null = null

  await page.goto('/auth')
  await expectHealthEndpoints(page)
  const authMode = await detectAuthMode(request)

  if (authMode === 'header') {
    auth = {
      mode: 'header',
      userId: resolveHeaderUserId(),
      tenantId: resolveHeaderTenantId(),
    }
  } else {
    auth = await authenticateThroughUi(page)
  }

  try {
    const dataset = await createDataset(request, page, auth)
    datasetId = dataset.id

    await page.goto(`/knowledge/ingestion?datasetId=${dataset.id}`)
    await expect(page.getByRole('heading', { name: '入库管理' })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText(dataset.name).first()).toBeVisible({ timeout: 60_000 })
    await selectFullIndexExecutionMode(page)

    const uploadResponsePromise = page.waitForResponse(
      (response) => {
        const url = new URL(response.url())
        return response.request().method() === 'POST' && url.pathname.replace(/\/$/, '') === '/api/v1/documents/upload-batch'
      },
      { timeout: 180_000 }
    )
    await page.locator('input[type="file"][multiple]').setInputFiles(FIXTURE_PATH)

    await expect(page.getByText(FIXTURE_FILENAME).first()).toBeVisible({ timeout: 30_000 })
    const ingestButton = page.getByRole('button', { name: '解析并建索引' })
    await expect(ingestButton).toBeEnabled({ timeout: 30_000 })
    await ingestButton.click()

    const uploadResponse = await uploadResponsePromise
    expect(uploadResponse.ok()).toBeTruthy()
    const uploadPayload = (await uploadResponse.json()) as {
      successful_count?: number
      failed_count?: number
      successful?: Array<{ document_id?: string }>
    }
    expect(uploadPayload.successful_count).toBe(1)
    expect(uploadPayload.failed_count).toBe(0)
    const documentId = String(uploadPayload.successful?.[0]?.document_id || '').trim()
    expect(documentId).toBeTruthy()
    await waitForDocumentCompletion(request, auth, documentId)

    await page.goto('/')
    const composer = page.getByPlaceholder('问点什么... (Shift + Enter 换行)')
    await expect(composer).toBeVisible({ timeout: 60_000 })
    await selectChatDatasetScope(page, dataset.name)
    await composer.fill('请返回刚上传文档中的 release token，并说明它来自哪个文件；务必给出知识库引用证据。')
    await page.getByRole('button', { name: '发送' }).click()

    await page.getByText('来源与证据').last().click()
    const evidencePanel = page.locator('details[open]').last()
    const evidenceCitationCard = evidencePanel.getByRole('button', {
      name: new RegExp(`^1\\s*${escapeRegExp(FIXTURE_FILENAME)}.*${escapeRegExp(FIXTURE_TOKEN)}`),
    })
    await expect(evidenceCitationCard).toBeVisible({ timeout: 90_000 })
    await expect(evidenceCitationCard).toContainText(FIXTURE_TOKEN)
  } finally {
    await cleanupDataset(request, auth, datasetId)
  }
})
