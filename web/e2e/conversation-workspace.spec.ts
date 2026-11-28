import { expect, test, type Page } from '@playwright/test'
import { installCommonApiMocks, type EnterpriseTelemetryMockState } from './enterprise-quality-telemetry.helpers'

const today = new Date().toISOString()
const firstConversationId = 'conversation-ui95-1'

async function fixture(page: Page, theme: 'light' | 'dark' = 'light') {
  const chatState: EnterpriseTelemetryMockState = { uploaded: true, parsingDocuments: [] }
  await installCommonApiMocks(page, chatState)
  await page.addInitScript((theme) => {
    localStorage.setItem('theme', theme)
    localStorage.setItem('mimirq.surfaceTheme', 'ocean')
    localStorage.removeItem('mimirq.themeColor')
  }, theme)
  const state = {
    failList: false,
    failRename: false,
    failDelete: false,
    conversations: [
      {
        id: firstConversationId,
        title: '食品安全合规分析与处置方案',
        last_message: '整理检测结果、适用条款与后续处置建议。',
        last_message_at: today,
        message_count: 2,
        created_at: today,
        updated_at: today,
      },
      {
        id: 'conversation-ui95-2',
        title: '跨部门协作手册中的交接要求与异常升级流程',
        last_message: '比较日常交接与紧急升级的责任边界。',
        last_message_at: today,
        message_count: 4,
        created_at: today,
        updated_at: today,
      },
    ],
  }
  await page.route('**/api/v1/rbac/me', (route) =>
    route.fulfill({
      json: {
        tenant_id: '00000000-0000-0000-0000-000000000000',
        account_id: 'conversation-review',
        role: 'owner',
        permissions: ['settings.read', 'settings.write'],
        is_active: true,
        is_current: true,
      },
    }),
  )
  await page.route('**/api/v1/datasets**', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'dataset-ui95-1',
            tenant_id: '00000000-0000-0000-0000-000000000000',
            name: '食品安全与质量管理',
            description: '检测报告、作业规范与质量管理手册',
            permission: 'me',
            ingestion_summary: { total_documents: 18, total_chunks: 246, total_size: 120000, total_characters: 46000 },
          },
          {
            id: 'dataset-ui95-2',
            tenant_id: '00000000-0000-0000-0000-000000000000',
            name: '企业协作与交接流程',
            permission: 'me',
            ingestion_summary: { total_documents: 6, total_chunks: 82, total_size: 30000, total_characters: 12000 },
          },
        ],
        total: 2,
      },
    }),
  )
  await page.route('**/api/v1/chat/conversations**', async (route) => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    if (url.pathname.endsWith('/messages')) {
      const conversationId = url.pathname.split('/').at(-2)
      return route.fulfill({
        json: {
          conversation_id: conversationId,
          returned: 2,
          has_more: false,
          messages: [
            {
              id: `${conversationId}-user`,
              role: 'user',
              content: '请整理食品安全检测结果，并说明后续处置建议。',
              created_at: today,
            },
            {
              id: `${conversationId}-assistant`,
              role: 'assistant',
              content:
                '## 检测结论\n\n报告中的关键指标均在适用限值内。建议保留原始记录，并完成以下检查：\n\n1. 核对批次与采样日期。\n2. 按作业规范归档检测结果。\n3. 对临界指标安排复检。\n\n后续处置应结合实际生产批次与最新适用标准。',
              created_at: today,
            },
          ],
        },
      })
    }
    if (url.pathname === '/api/v1/chat/conversations' && method === 'GET') {
      if (state.failList) return route.fulfill({ status: 503, json: { detail: '历史记录暂不可用' } })
      const query = url.searchParams.get('q') || ''
      const items = state.conversations.filter((conversation) => conversation.title.includes(query))
      return route.fulfill({
        json: { items, total: items.length, returned: items.length, has_more: false, next_skip: null },
      })
    }
    const conversationId = url.pathname.split('/').at(-1)
    if (method === 'PATCH') {
      if (state.failRename) return route.fulfill({ status: 503, json: { detail: '标题暂未保存' } })
      const conversation = state.conversations.find((item) => item.id === conversationId)!
      conversation.title = route.request().postDataJSON().title
      return route.fulfill({ json: conversation })
    }
    if (method === 'DELETE') {
      if (state.failDelete) return route.fulfill({ status: 503, json: { detail: '删除暂不可用' } })
      state.conversations = state.conversations.filter((item) => item.id !== conversationId)
      return route.fulfill({ status: 204, body: '' })
    }
    return route.fulfill({ json: {} })
  })
  return { state, chatState }
}

async function shot(page: Page, name: string) {
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), animations: 'disabled' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), name).toBe(true)
}

test('conversation workspace keeps scope, retrieval and stream actions usable', async ({ page }) => {
  const { chatState } = await fixture(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  const input = page.getByRole('textbox', { name: '消息输入框', exact: true })
  await expect(input).toBeVisible({ timeout: 60000 })
  await expect(page.getByRole('button', { name: '食品安全与质量管理', exact: true })).toBeEnabled()
  await expect(input).toBeFocused()
  const border = await input.locator('..').evaluate((element) => {
    const probe = document.createElement('span')
    probe.style.borderColor = 'color-mix(in oklab, hsl(var(--foreground)) 30%, transparent)'
    element.append(probe)
    const colors = {
      actual: getComputedStyle(element).borderTopColor,
      expected: getComputedStyle(probe).borderTopColor,
    }
    probe.remove()
    return colors
  })
  expect(border.actual).toBe(border.expected)
  const starters = page
    .getByRole('button', { name: /梳理业务流程/ })
    .locator('..')
    .getByRole('button')
  await expect(starters).toHaveCount(4)
  const starterSurfaces = await starters.evaluateAll((buttons) =>
    buttons.map((button) => getComputedStyle(button).backgroundColor),
  )
  expect(new Set(starterSurfaces).size).toBe(1)
  await expect(starters.first()).toHaveCSS('border-top-width', '1px')
  await shot(page, 'chat-desktop')
  await page.setViewportSize({ width: 390, height: 844 })
  await shot(page, 'chat-mobile')
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.getByRole('button', { name: '食品安全与质量管理', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '筛选数据集名称或编号', exact: true })).toBeVisible()
  await shot(page, 'chat-dataset-picker')
  await page.getByRole('button', { name: /企业协作与交接流程/ }).click()
  await page.getByRole('button', { name: '检索设置', exact: true }).click()
  await shot(page, 'chat-retrieval')
  await page.getByText('高级选项', { exact: true }).click()
  await expect(page.locator('#chat-other-retrieval-mode')).toBeInViewport({ ratio: 1 })
  await shot(page, 'chat-retrieval-advanced')
  await page.setViewportSize({ width: 390, height: 620 })
  await shot(page, 'chat-retrieval-mobile')
  const retrievalBounds = await page.locator('#chat-retrieval-settings').boundingBox()
  expect(retrievalBounds).not.toBeNull()
  expect(retrievalBounds!.y + retrievalBounds!.height).toBeLessThanOrEqual(620)
  await page.keyboard.press('Escape')
  await page.setViewportSize({ width: 1440, height: 900 })
  await input.fill('请总结文档中的质量管理要求。')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await expect(page.getByText('已完成智能对话验证。', { exact: true })).toBeVisible()
  await expect(page.getByText('请总结文档中的质量管理要求。', { exact: true })).toBeVisible()
  await expect.poll(() => chatState.chatRequests?.at(-1)?.message).toBe('请总结文档中的质量管理要求。')
  await shot(page, 'chat-answer')
  await page.setViewportSize({ width: 390, height: 844 })
  await shot(page, 'chat-answer-mobile')
})

test('empty text indexes show an inline guidance link on desktop and phone', async ({ page }) => {
  await fixture(page)
  await page.route('**/api/v1/datasets**', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'dataset-empty',
            name: '待入库资料',
            permission: 'me',
            ingestion_summary: {
              total_documents: 0,
              total_chunks: 0,
              total_size: 0,
              total_characters: 0,
            },
          },
        ],
        total: 1,
      },
    }),
  )
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('button', { name: '待入库资料', exact: true })).toBeEnabled({ timeout: 60000 })
  const guidance = page.getByRole('status').filter({ hasText: '此数据集暂无文本切块' })
  const inspect = guidance.getByRole('link', { name: '查看文档', exact: true })
  await expect(inspect).toHaveAttribute('href', '/knowledge?dataset=dataset-empty')
  await expect(guidance).toHaveCSS('border-top-width', '1px')
  await shot(page, 'chat-empty-index-desktop')
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(inspect).toBeInViewport({ ratio: 1 })
  await shot(page, 'chat-empty-index-mobile')
  await inspect.click()
  await expect(page).toHaveURL(/\/knowledge\?dataset=dataset-empty$/, { timeout: 60_000 })
})

test('history keeps list, reading and mobile navigation available', async ({ page }) => {
  const { state } = await fixture(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/history', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '食品安全合规分析与处置方案', exact: true })).toBeVisible({
    timeout: 60000,
  })
  await expect(page.getByText('检测结论', { exact: true })).toBeVisible()
  await shot(page, 'history-desktop')
  await page.getByRole('button', { name: '更多对话操作', exact: true }).click()
  await shot(page, 'history-actions')
  await page.keyboard.press('Escape')
  await page
    .locator('[data-history-sidebar]')
    .getByRole('button', { name: /食品安全合规分析与处置方案/ })
    .click()
  await expect(page).toHaveURL(new RegExp(`id=${firstConversationId}`))
  await page.setViewportSize({ width: 1024, height: 768 })
  await shot(page, 'history-narrow-desktop')
  await page.setViewportSize({ width: 390, height: 844 })
  await shot(page, 'history-reading-mobile')
  await page.getByRole('button', { name: '展开历史列表', exact: true }).click()
  await expect(page.locator('[data-history-sidebar]')).toBeVisible()
  await shot(page, 'history-list-mobile')
  const sidebar = page.locator('[data-history-sidebar]')
  const row = sidebar.getByRole('button', { name: /食品安全合规分析与处置方案/ }).locator('..')
  await row.getByRole('button', { name: '删除对话', exact: true }).click()
  await expect(row.getByRole('button', { name: '确认删除对话', exact: true })).toHaveText('确认删除对话')
  await expect(row.getByRole('button', { name: '取消删除', exact: true })).toHaveText('取消删除')
  await expect(row.getByText('食品安全合规分析与处置方案', { exact: true })).toBeVisible()
  await row.getByRole('button', { name: '取消删除', exact: true }).click()
  await expect(row.getByRole('button', { name: '删除对话', exact: true })).toBeVisible()
  await row.getByRole('button', { name: '删除对话', exact: true }).click()
  await shot(page, 'history-delete-confirmation')
  state.failDelete = true
  await row.getByRole('button', { name: '确认删除对话', exact: true }).click()
  await expect(page.getByText(/删除暂不可用/)).toBeVisible()
  await expect(row.getByRole('button', { name: '确认删除对话', exact: true })).toBeEnabled()
  state.failDelete = false
  await row.getByRole('button', { name: '确认删除对话', exact: true }).click()
  await expect(sidebar.getByRole('button', { name: /食品安全合规分析与处置方案/ })).not.toBeVisible()
  await sidebar.getByRole('textbox', { name: '搜索对话', exact: true }).fill('不存在的对话')
  await expect(sidebar.getByText('没有找到匹配的对话', { exact: true })).toBeVisible()
  await shot(page, 'history-filtered-empty')
})

test('conversation and history keep the dark work surface readable', async ({ page }) => {
  await fixture(page, 'dark')
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('textbox', { name: '消息输入框', exact: true })).toBeVisible({ timeout: 60000 })
  await shot(page, 'chat-dark')
  await page.goto('/history', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '食品安全合规分析与处置方案', exact: true })).toBeVisible({
    timeout: 60000,
  })
  await shot(page, 'history-dark')
})

test('history retains a failed title edit and reads a saved title after reload', async ({ page }) => {
  const { state } = await fixture(page)
  await page.goto(`/history?id=${firstConversationId}`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: state.conversations[0].title, exact: true })).toBeVisible({
    timeout: 60000,
  })
  await page.getByRole('button', { name: '更多对话操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '重命名', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '重命名对话', exact: true })
  await dialog.getByRole('textbox', { name: '对话标题', exact: true }).fill('食品检测复核与归档要求')
  state.failRename = true
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('标题暂未保存')
  await expect(dialog.getByRole('textbox', { name: '对话标题', exact: true })).toHaveValue('食品检测复核与归档要求')
  await page.setViewportSize({ width: 390, height: 620 })
  await shot(page, 'history-rename-failure')
  state.failRename = false
  state.failList = true
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('名称已保存，历史列表刷新失败')
  expect(state.conversations[0].title).toBe('食品检测复核与归档要求')
  state.failList = false
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.getByRole('heading', { name: '食品检测复核与归档要求', exact: true })).toBeVisible()
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '食品检测复核与归档要求', exact: true })).toBeVisible({
    timeout: 60000,
  })
})

test('history distinguishes an empty archive from a failed read', async ({ page }) => {
  const { state } = await fixture(page)
  state.conversations = []
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/history', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('暂无问答记录', { exact: true })).toBeVisible({ timeout: 60000 })
  const empty = page.locator('[data-history-main-empty="true"]')
  await expect(empty.getByRole('link', { name: '新建对话', exact: true })).toHaveAttribute('href', '/')
  await expect(empty.getByRole('link', { name: '前往知识库', exact: true })).toHaveAttribute('href', '/knowledge')
  await expect(empty.getByRole('complementary', { name: '问答记录与引用', exact: true })).toBeVisible()
  await expect(empty.locator(':scope > section')).toHaveCSS('border-top-width', '0px')
  await shot(page, 'history-empty')
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(empty.getByRole('link', { name: '新建对话', exact: true })).toBeInViewport({ ratio: 1 })
  await shot(page, 'history-empty-mobile')
  state.failList = true
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.locator('main').getByRole('alert').filter({ hasText: '历史记录暂不可用' }).last()).toBeVisible({
    timeout: 60000,
  })
  await shot(page, 'history-read-error')
})
