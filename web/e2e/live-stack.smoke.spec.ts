import path from 'node:path'

import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const LIVE_STACK_ENABLED = process.env.PLAYWRIGHT_LIVE_STACK === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const FIXTURE_NAME = 'enterprise-telemetry-sample.md'
const DOCUMENT_POLL_TIMEOUT_MS = 300_000

type LiveDocument = {
  id?: string
  filename?: string
  name?: string
  status?: string
  error_message?: string | null
  processing_progress?: number | null
  current_stage?: string | null
  created_at?: string | null
}

function buildLiveHeaders(tenantId: string, userId: string): Record<string, string> {
  return {
    'X-Tenant-ID': tenantId,
    'X-User-ID': userId,
  }
}

function sortDocumentsByCreatedAtDesc(items: LiveDocument[]): LiveDocument[] {
  return [...items].sort((left, right) => {
    const leftTs = Date.parse(left.created_at || '') || 0
    const rightTs = Date.parse(right.created_at || '') || 0
    return rightTs - leftTs
  })
}

async function listDocuments(
  request: APIRequestContext,
  {
    apiBase,
    tenantId,
    userId,
    limit = 20,
  }: {
    apiBase: string
    tenantId: string
    userId: string
    limit?: number
  }
): Promise<LiveDocument[]> {
  const response = await request.get(`${apiBase}/api/v1/documents/?limit=${limit}`, {
    headers: buildLiveHeaders(tenantId, userId),
  })
  if (!response.ok()) {
    return []
  }

  const data = (await response.json()) as { items?: LiveDocument[] }
  return data.items || []
}

async function waitForNewDocument(
  request: APIRequestContext,
  {
    apiBase,
    tenantId,
    userId,
    filename,
    existingIds,
  }: {
    apiBase: string
    tenantId: string
    userId: string
    filename: string
    existingIds: Set<string>
  }
): Promise<LiveDocument> {
  let uploaded: LiveDocument | null = null

  await expect
    .poll(async () => {
      const items = sortDocumentsByCreatedAtDesc(
        await listDocuments(request, {
          apiBase,
          tenantId,
          userId,
          limit: 50,
        })
      )
      uploaded =
        items.find((item) => {
          const id = String(item.id || '').trim()
          const name = String(item.filename || item.name || '').trim()
          return Boolean(id && name.includes(filename) && !existingIds.has(id))
        }) || null
      return String(uploaded?.id || '').trim()
    }, {
      timeout: 120_000,
    })
    .not.toBe('')

  if (!uploaded) {
    throw new Error(`Uploaded document was not found after polling: ${filename}`)
  }

  return uploaded
}

async function waitForDocumentCompleted(
  request: APIRequestContext,
  {
    apiBase,
    tenantId,
    userId,
    documentId,
  }: {
    apiBase: string
    tenantId: string
    userId: string
    documentId: string
  }
): Promise<LiveDocument> {
  let current: LiveDocument | null = null

  await expect
    .poll(async () => {
      const response = await request.get(`${apiBase}/api/v1/documents/${documentId}`, {
        headers: buildLiveHeaders(tenantId, userId),
      })
      if (!response.ok()) {
        return `http-${response.status()}`
      }

      current = (await response.json()) as LiveDocument
      const status = String(current.status || '').trim().toLowerCase()
      if (status === 'error' || status === 'failed') {
        throw new Error(
          `Document ${documentId} entered ${status}: ${String(current.error_message || 'unknown error')}`
        )
      }
      return status
    }, {
      timeout: DOCUMENT_POLL_TIMEOUT_MS,
    })
    .toBe('completed')

  if (!current) {
    throw new Error(`Document ${documentId} was not available after polling`)
  }

  return current
}

async function waitForConversationId(page: Page): Promise<string> {
  await expect
    .poll(() => new URL(page.url()).searchParams.get('conversation') || '', {
      timeout: 180_000,
    })
    .not.toBe('')

  return new URL(page.url()).searchParams.get('conversation') || ''
}

async function waitForAssistantReply(
  request: APIRequestContext,
  {
    apiBase,
    tenantId,
    userId,
    conversationId,
  }: {
    apiBase: string
    tenantId: string
    userId: string
    conversationId: string
  }
): Promise<void> {
  const headers = buildLiveHeaders(tenantId, userId)

  await expect
    .poll(async () => {
      const response = await request.get(`${apiBase}/api/v1/chat/conversations/${conversationId}/messages?limit=20`, {
        headers,
      })
      if (!response.ok()) {
        return 0
      }

      const data = (await response.json()) as { messages?: Array<{ role?: string; content?: string }> }
      return data.messages?.length || 0
    }, {
      timeout: 180_000,
    })
    .toBeGreaterThanOrEqual(2)

  await expect
    .poll(async () => {
      const response = await request.get(`${apiBase}/api/v1/chat/conversations/${conversationId}/messages?limit=20`, {
        headers,
      })
      if (!response.ok()) {
        return ''
      }

      const data = (await response.json()) as { messages?: Array<{ role?: string; content?: string }> }
      const assistantMessage = [...(data.messages || [])]
        .reverse()
        .find((message) => message.role === 'assistant' && (message.content || '').trim())
      return (assistantMessage?.content || '').trim()
    }, {
      timeout: 180_000,
    })
    .toMatch(/\S/)
}

test.describe('live stack smoke', () => {
  test.skip(!LIVE_STACK_ENABLED, 'Requires the live stack runner')

  test('uploads, parses, opens the viewer, chats, and runs a command-menu handoff against the live stack', async ({
    page,
    request,
  }) => {
    const filePath = path.resolve(__dirname, 'fixtures/enterprise-telemetry-sample.md')
    const apiBase = process.env.PLAYWRIGHT_LIVE_API_URL || 'http://127.0.0.1:8000'
    const tenantId = process.env.PLAYWRIGHT_LIVE_TENANT_ID || process.env.NEXT_PUBLIC_TENANT_ID || DEFAULT_TENANT_ID
    const userId = process.env.PLAYWRIGHT_LIVE_USER_ID || process.env.NEXT_PUBLIC_USER_ID || DEFAULT_USER_ID
    const existingDocumentIds = new Set(
      (await listDocuments(request, { apiBase, tenantId, userId, limit: 50 })).map((item) => String(item.id || '').trim())
    )
    let documentId = ''

    await test.step('upload and parse a real document', async () => {
      await page.goto('/parsing', { waitUntil: 'networkidle' })
      await page.getByRole('heading', { name: '文档解析' }).waitFor({ timeout: 120_000 })

      const fileInput = page.locator('input[type="file"][multiple]:not([webkitdirectory])')
      await fileInput.setInputFiles(filePath)

      await page.getByText('已加入队列：1 个文件').waitFor({ timeout: 30_000 })
      await page.getByRole('button', { name: '开始解析' }).click()
      const uploaded = await waitForNewDocument(request, {
        apiBase,
        tenantId,
        userId,
        filename: FIXTURE_NAME,
        existingIds: existingDocumentIds,
      })
      documentId = String(uploaded.id || '')
      expect(documentId).toBeTruthy()

      await waitForDocumentCompleted(request, {
        apiBase,
        tenantId,
        userId,
        documentId,
      })

      await page.getByText(/^0 处理$/).waitFor({ timeout: 120_000 })
      await page.getByText(/^1 完成$/).waitFor({ timeout: 120_000 })
    })

    await test.step('open the real document viewer and keep state across reload', async () => {
      await page.goto(`/?doc=${encodeURIComponent(documentId)}`, { waitUntil: 'networkidle' })
      await page.getByRole('heading', { name: FIXTURE_NAME }).waitFor({ timeout: 120_000 })

      const expand = page.getByRole('button', { name: '展开' })
      if (await expand.count()) {
        await expand.click()
        const chunksTab = page.getByRole('tab', { name: '智能切片' })
        await chunksTab.waitFor({ timeout: 30_000 })
        await chunksTab.click()
        await page.reload({ waitUntil: 'networkidle' })
        await page.getByRole('heading', { name: FIXTURE_NAME }).waitFor({ timeout: 120_000 })
        await page.getByRole('tab', { name: '智能切片' }).waitFor({ timeout: 30_000 })
      }
    })

    await test.step('send a real chat request for the uploaded content', async () => {
      await page.goto('/', { waitUntil: 'networkidle' })
      const input = page.getByPlaceholder('问点什么... (Shift + Enter 换行)')
      await input.waitFor({ timeout: 120_000 })
      await input.fill('请总结刚上传文档的重点。')
      await input.press('Enter')
      await expect(input).toHaveValue('', { timeout: 30_000 })

      const conversationId = await waitForConversationId(page)
      await waitForAssistantReply(request, {
        apiBase,
        tenantId,
        userId,
        conversationId,
      })
    })

    await test.step('run a command-menu handoff into the real chat surface', async () => {
      const prompt = '请帮我总结当前页面有哪些可继续操作的重点。'

      await page.goto('/', { waitUntil: 'networkidle' })
      await page.getByPlaceholder('问点什么... (Shift + Enter 换行)').waitFor({ timeout: 120_000 })
      await page.getByRole('button', { name: '打开命令搜索' }).click()

      const commandDialog = page.getByRole('dialog')
      await commandDialog.waitFor({ timeout: 30_000 })

      const commandInput = commandDialog.getByRole('combobox')
      await commandInput.fill(prompt)
      await page.getByRole('option', { name: /执行自然语言指令/ }).waitFor({ timeout: 30_000 })
      await commandInput.press('Enter')

      const conversationId = await waitForConversationId(page)
      await waitForAssistantReply(request, {
        apiBase,
        tenantId,
        userId,
        conversationId,
      })
    })
  })
})
