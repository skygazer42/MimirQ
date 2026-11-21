import { expect, test, type Page } from '@playwright/test'

import type { Conversation, Message } from '../types/chat'
import type { Dataset } from '../types/datasets'
import type { Document } from '../types/documents'

test.use({ serviceWorkers: 'block' })

type JsonResponse = { status: number; json: unknown }

async function mockWorkspaceApi(page: Page, findResponse: (url: URL) => JsonResponse | undefined) {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace(/\/$/, '')
    const headers = {
      'access-control-allow-origin': '*',
      'access-control-allow-headers': '*',
      'access-control-allow-methods': 'GET, POST, OPTIONS',
    }
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers })
      return
    }
    const response = findResponse(url)
    if (response) {
      await route.fulfill({ ...response, headers })
    } else if (path.endsWith('/meta')) {
      await route.fulfill({
        status: 200,
        json: {
          name: 'Ragvia API',
          api_version: 'browser-contract-check',
          build: { sha: 'browser-contract-check' },
          features: { auth_mode: 'header', vector_backend: 'memory', task_queue_enabled: false },
        },
        headers,
      })
    } else if (path.endsWith('/health/ready')) {
      await route.fulfill({ status: 200, json: { ok: true, status: 'ready' }, headers })
    } else if (path.endsWith('/rbac/me')) {
      await route.fulfill({
        status: 200,
        json: {
          account_id: 'browser-viewer',
          tenant_id: '22222222-2222-4222-8222-222222222222',
          role: 'viewer',
          is_active: true,
          permissions: [],
        },
        headers,
      })
    } else if (path.endsWith('/datasets') || path.endsWith('/documents') || path.endsWith('/connectors/runs')) {
      await route.fulfill({ status: 200, json: { total: 0, items: [] }, headers })
    } else if (path.endsWith('/documents/stats')) {
      await route.fulfill({ status: 200, json: { total: 0, by_status: {}, total_chunks: 0, total_size: 0 }, headers })
    } else {
      await route.fulfill({ status: 503, json: { message: 'Unavailable in isolated browser check' }, headers })
    }
  })
}

test('continues a conversation after visiting its paginated history', async ({ page }) => {
  const conversationId = '33333333-3333-4333-8333-333333333333'
  const conversation: Conversation = {
    id: conversationId,
    title: '缓存合同验证',
    message_count: 1,
    created_at: '2026-11-12T00:00:00Z',
    updated_at: '2026-11-12T00:00:00Z',
  }
  const messageLimits: Array<string | null> = []
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await mockWorkspaceApi(page, (url) => {
    if (url.pathname.endsWith('/chat/conversations')) {
      return { status: 200, json: { total: 1, items: [conversation], returned: 1, has_more: false } }
    }
    if (url.pathname.endsWith(`/chat/conversations/${conversationId}/messages`)) {
      const limit = url.searchParams.get('limit')
      messageLimits.push(limit)
      const message: Message = {
        id: '44444444-4444-4444-8444-444444444444',
        role: 'assistant',
        content: limit === null ? '完整聊天历史' : '分页历史内容',
        created_at: '2026-11-12T00:00:00Z',
        citations: [],
        steps: [],
      }
      return {
        status: 200,
        json: { conversation_id: conversationId, messages: [message], returned: 1, has_more: false },
      }
    }
  })

  await page.goto(`/zh-CN/history?id=${conversationId}`)
  await expect(page.getByText('分页历史内容', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: '继续当前对话', exact: true }).click()
  await expect(page.getByText('完整聊天历史', { exact: true }).first()).toBeVisible()
  expect(messageLimits.some((limit) => limit !== null)).toBe(true)
  expect(messageLimits).toContain(null)
  expect(pageErrors).toEqual([])
})

test('retries a dataset failure through the visible keyboard control', async ({ page }) => {
  let failDatasets = true
  const dataset: Dataset = {
    id: '55555555-5555-4555-8555-555555555555',
    tenant_id: '22222222-2222-4222-8222-222222222222',
    name: '验证数据集',
    permission: 'all_team_members',
  }
  await mockWorkspaceApi(page, (url) => {
    if (url.pathname.replace(/\/$/, '').endsWith('/datasets')) {
      return failDatasets
        ? {
            status: 503,
            json: { message: '数据集服务不可用', request_id: 'a'.repeat(64) },
          }
        : { status: 200, json: { total: 1, items: [dataset] } }
    }
  })

  await page.goto('/zh-CN/knowledge/evidence')
  await page.getByRole('button', { name: '高级工具', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '证据高级工具' })
  const alert = dialog.getByRole('alert').filter({ hasText: '数据集服务不可用' })
  await expect(alert).toBeVisible({ timeout: 15000 })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: '../.frontend-structure/20261112-full-frontend-guidelines/dataset-error-mobile.png' })
  expect(await alert.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await expect(dialog.getByRole('button', { name: '重试', exact: true })).toBeInViewport({ ratio: 1 })

  failDatasets = false
  const retry = dialog.getByRole('button', { name: '重试', exact: true })
  await retry.focus()
  await page.keyboard.press('Tab')
  await expect(retry).not.toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(retry).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(alert).toHaveCount(0)
  const selector = dialog.getByRole('combobox', { name: '数据集', exact: true })
  await expect(selector).toBeEnabled()
  await selector.click()
  await page.getByRole('option', { name: '验证数据集', exact: true }).click()
  await expect(selector).toContainText('验证数据集')
})

test('replaces idle task content after the shared auth scope invalidation', async ({ page }) => {
  let hasNewTasks = false
  await mockWorkspaceApi(page, (url) => {
    const path = url.pathname.replace(/\/$/, '')
    if (path.endsWith('/documents')) {
      const document: Document = {
        id: hasNewTasks ? '77777777-7777-4777-8777-777777777777' : '66666666-6666-4666-8666-666666666666',
        filename: hasNewTasks ? 'scope-b.pdf' : 'scope-a.pdf',
        file_type: 'pdf',
        file_size: 1024,
        status: 'processing',
        processing_progress: 30,
        processing_attempts: 1,
        publication_status: 'draft',
        chunk_count: 0,
        total_characters: 0,
        created_at: '2026-11-12T00:00:00Z',
        updated_at: '2026-11-12T00:00:00Z',
      }
      return { status: 200, json: { total: 1, items: [document] } }
    }
    if (path.endsWith('/documents/stats')) {
      return { status: 200, json: { total: 1, by_status: { processing: 1 }, total_chunks: 0, total_size: 1024 } }
    }
  })

  await page.goto('/zh-CN/knowledge')
  await page.getByRole('button', { name: '任务中心', exact: true }).click()
  await expect(page.locator('[data-task-center-panel]')).toContainText('scope-a.pdf')
  hasNewTasks = true
  await page.evaluate(() => window.dispatchEvent(new Event('mimirq:auth-scope-changed')))
  await expect(page.locator('[data-task-center-panel]')).toHaveCount(0)
  await page.getByRole('button', { name: '任务中心', exact: true }).click()
  await expect(page.locator('[data-task-center-panel]')).toContainText('scope-b.pdf')
  await expect(page.locator('[data-task-center-panel]')).not.toContainText('scope-a.pdf')
})

test('searches server results, reports failures and retires the command menu on an auth scope change', async ({
  page,
}) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await mockWorkspaceApi(page, (url) => {
    const query = url.searchParams.get('q')
    if (!query) return
    if (url.pathname.endsWith('/documents')) {
      if (query === '查询失败') return { status: 503, json: { message: '搜索服务暂不可用' } }
      return {
        status: 200,
        json: { total: 1, items: [{ id: 'command-document', filename: '正文命中的资料.pdf', file_type: 'pdf' }] },
      }
    }
    if (url.pathname.endsWith('/datasets')) return { status: 200, json: { total: 0, items: [] } }
    if (url.pathname.endsWith('/chat/conversations')) {
      return {
        status: 200,
        json: {
          total: 1,
          items: [{ id: 'command-conversation', title: null, last_message: null, last_message_at: null }],
        },
      }
    }
  })

  await page.goto('/zh-CN/knowledge')
  await expect(page.getByRole('heading', { name: '知识库', exact: true })).toBeVisible()
  await page.keyboard.press('Control+k')
  const dialog = page.getByRole('dialog', { name: '命令中心', exact: true })
  const input = dialog.getByRole('combobox')
  await expect(input).toBeFocused()
  await input.fill('内容线索')
  await expect(dialog.getByText('正文命中的资料.pdf', { exact: true })).toBeVisible()
  await expect(dialog.getByText('未命名对话', { exact: true })).toBeVisible()

  await input.fill('查询失败')
  await expect(dialog.getByRole('alert').filter({ hasText: '搜索服务暂不可用' })).toBeVisible()
  await expect(dialog.getByText('未找到文档', { exact: true })).toHaveCount(0)

  await page.evaluate(() => window.dispatchEvent(new Event('mimirq:auth-scope-changed')))
  await expect(dialog).toHaveCount(0)
  await page.keyboard.press('Control+k')
  await expect(input).toHaveValue('')
  await input.fill('/report')
  await expect(dialog.getByText('选择数据集，进入文档预检查看和导出报告', { exact: true })).toBeVisible()
  await page.keyboard.press('Enter')
  await page.waitForURL(/\/datasets$/)
  expect(pageErrors).toEqual([])
})

test('keeps invalid pipeline imports open and reloads a successfully imported preference', async ({ page }) => {
  await page.addInitScript(() => {
    if (localStorage.getItem('mimirq_pipeline_options') === null) {
      localStorage.setItem('mimirq_pipeline_options', JSON.stringify({ enabled: true, options: { chunk_size: 4096 } }))
    }
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (value: string) => sessionStorage.setItem('pipeline-export-test', value),
      },
    })
  })
  await mockWorkspaceApi(page, () => undefined)

  await page.goto('/zh-CN/data-governance')
  await page.getByRole('button', { name: '治理配置', exact: true }).click()
  const configuration = page.getByRole('dialog', { name: '治理配置', exact: true })
  const pipelineOptions = configuration.locator('section').filter({
    has: page.getByRole('heading', { name: '清洗规则', exact: true }),
  })
  await pipelineOptions.getByRole('button', { name: '导入', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '导入管线 JSON', exact: true })
  await dialog.getByRole('textbox').fill('null')
  await dialog.getByRole('button', { name: '导入', exact: true }).click()

  await expect(page.getByText('Invalid options shape', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('textbox')).toHaveValue('null')
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('mimirq_pipeline_options')!))).toMatchObject({
    enabled: true,
    options: { chunk_size: 4096 },
  })

  await dialog.getByRole('textbox').fill('{"enabled":true,"options":{"chunk_size":2048}}')
  await dialog.getByRole('button', { name: '导入', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect
    .poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('mimirq_pipeline_options')!)))
    .toMatchObject({ enabled: true, options: { chunk_size: 2048 } })

  await page.reload()
  await page.getByRole('button', { name: '治理配置', exact: true }).click()
  await pipelineOptions.getByRole('button', { name: '导出', exact: true }).click()
  await expect
    .poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem('pipeline-export-test')!)))
    .toMatchObject({ enabled: true, options: { chunk_size: 2048 } })
})

test('restores cached file metadata and keeps document close and resume actions usable', async ({ page }) => {
  const tenantId = '22222222-2222-4222-8222-222222222222'
  const userId = '33333333-3333-4333-8333-333333333333'
  const documentId = '88888888-8888-4888-8888-888888888888'
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.addInitScript(
    ({ tenantId, userId, documentId }) => {
      sessionStorage.setItem('mimirq_access_token', 'store-review-token')
      sessionStorage.setItem('mimirq_token_expires_at', String(Date.now() + 3_600_000))
      localStorage.setItem('mimirq_tenant_id', tenantId)
      localStorage.setItem('mimirq_user_id', userId)
      const scope = `${tenantId}:${userId}`
      localStorage.setItem(
        'mimirq_document_view_v1',
        JSON.stringify({
          version: 0,
          state: {
            authScope: scope,
            isOpen: true,
            documentId,
            activeTab: 'text',
            documentLayouts: null,
            lastOpenedTarget: { documentId, activeTab: 'text' },
            closeDocument: 'cached data',
          },
        }),
      )
      localStorage.setItem(
        `mimirq_parsed_files:${scope}`,
        JSON.stringify({
          version: 0,
          state: {
            files: [
              {},
              {
                id: '77777777-7777-4777-8777-777777777777',
                filename: 'Saved local note.md',
                fileType: 'md',
                fileSize: 0,
                markdownContent: '',
                parsedAt: '',
                parser: 'test',
                source: 'parsing_workspace',
                status: 'parsed',
              },
            ],
            folders: [],
            activeFolderId: 'root',
            getFile: 'cached data',
          },
        }),
      )
    },
    { tenantId, userId, documentId },
  )
  await mockWorkspaceApi(page, (url) => {
    if (url.pathname.endsWith(`/documents/${documentId}`)) {
      return {
        status: 200,
        json: {
          id: documentId,
          filename: 'stored-view.md',
          file_type: 'md',
          file_size: 0,
          status: 'completed',
          publication_status: 'draft',
          chunk_count: 0,
          total_characters: 23,
          created_at: '2026-11-12T00:00:00Z',
          updated_at: '2026-11-12T00:00:00Z',
        },
      }
    }
    if (url.pathname.endsWith(`/documents/${documentId}/parsed-content`)) {
      return {
        status: 200,
        json: {
          document_id: documentId,
          available: true,
          markdown_content: '# Restored preview body',
          original_markdown_content: '# Restored preview body',
          persisted_meta: {},
          markdown_truncated: false,
          original_markdown_truncated: false,
          max_chars: 200_000,
        },
      }
    }
    if (url.pathname.endsWith(`/documents/${documentId}/chunks`)) {
      return { status: 200, json: { total: 0, items: [] } }
    }
  })

  await page.goto('/zh-CN/data-governance')
  await expect(page.getByText('Saved local note.md', { exact: true }).first()).toBeVisible()
  await page.getByRole('link', { name: '知识库', exact: true }).click()
  await page.waitForURL(/\/knowledge$/)
  const heading = page.getByRole('heading', { name: 'stored-view.md', exact: true })
  await expect(heading).toBeVisible()
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(heading).toHaveCount(0)

  await page.keyboard.press('Control+k')
  await page.getByRole('combobox').fill('/resume')
  await page.keyboard.press('Enter')
  await page.waitForURL((url) => url.pathname === '/')
  await expect(heading).toBeVisible()
  expect(pageErrors).toEqual([])
})
