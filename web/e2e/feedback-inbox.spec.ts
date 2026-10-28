import path from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

const evidence = path.resolve(__dirname, '../../artifacts/rebrand/feedback-inbox-v1')
function makeFeedback(index: number) {
  return {
    id: `feedback-${index}`, tenant_id: 'tenant-test', conversation_id: `conversation-${index}`, message_id: `message-${index}`, account_id: `user_${9848 - index}`, rating: index % 4 === 0 ? 5 : index % 3 === 0 ? 3 : 2,
    conversation_title: index === 1 ? '如何配置知识库的分段策略以提升召回效果？' : `知识库反馈问题 ${index}`,
    reason: index === 1 ? '回答不完整，没有具体的配置示例，引用也没有覆盖参数说明。' : `需要核对这条回答的来源和适用范围 ${index}`,
    message_content: '分段策略会影响检索结果。可以结合文档结构、内容长度和实际问题选择合适的分段方式。\n\n对于说明文档，建议优先保留标题和段落的完整性；对长段落，可以设置适当的重叠，减少上下文在边界处被截断的情况。\n\n完成配置后，可以通过检索测试比较结果，再根据命中片段调整策略。',
    expected_answer: '1. 说明应该在哪个设置入口调整策略，以及这些设置作用于整个知识库、哪些作用于单次入库。\n2. 给出一份可核对的分段配置示例，解释长度、重叠及计量单位，并注明适用的文档类型。\n3. 提供原始资料的步骤：使用相同问题比较命中片段，检查引用覆盖，再决定是否重新入库。',
    tags: ['配置示例', '引用不足'], extra: { source: index % 2 ? 'web' : 'api', feedback_issue: '答案不完整', dataset_name: '产品使用文档', archived: index > 9 }, created_at: new Date(Date.now() - index * 3_600_000).toISOString(), updated_at: new Date().toISOString(),
  }
}
async function json(route: Route, body: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }) }
async function fixture(page: Page) {
  await installCommonApiMocks(page, { uploaded: false })
  const state = { records: Array.from({ length: 12 }, (_, index) => makeFeedback(index + 1)), failArchive: false, failList: false, holdCase: null as null | Promise<void>, writes: [] as string[] }
  await page.addInitScript(() => { if (!localStorage.getItem('theme')) localStorage.setItem('theme', 'light'); localStorage.setItem('mimirq.surfaceTheme', 'ocean'); localStorage.setItem('mimirq.themeColor', '#20262e') })
  await page.route('**/api/v1/feedback/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/messages/enriched')) {
      if (state.failList) return json(route, { detail: '反馈服务暂不可用' }, 503)
      const skip = Number(url.searchParams.get('skip') || 0); const limit = Number(url.searchParams.get('limit') || 200)
      return json(route, { total: state.records.length, items: state.records.slice(skip, skip + limit) })
    }
    if (url.pathname.endsWith('/loop/candidates')) return json(route, { schema: 'test', summary: { feedback_total: 12 }, hard_negative_records: [{ query: '分段策略', source_feedback_id: 'feedback-1' }], training_triples: [], eval_case_candidates: [], rules_suggestions: { glossary_suggestions: [{ token: '分段', expansion: '文档切分策略' }] } })
    const id = url.pathname.split('/messages/')[1]?.split('/')[0]
    if (route.request().method() === 'PATCH') {
      if (state.failArchive) return json(route, { detail: '归档服务暂不可用' }, 503)
      const record = state.records.find(item => item.id === id)!
      record.extra.archived = route.request().postDataJSON().archived
      state.writes.push(`archive:${id}`)
      return json(route, record)
    }
    if (url.pathname.endsWith('/to-regression-case')) {
      state.writes.push(`case:${id}`)
      if (state.holdCase) await state.holdCase
      return json(route, { id: `case-${id}` })
    }
    return route.fallback()
  })
  await page.route('**/api/v1/chat/conversations/*/messages*', route => {
    const id = new URL(route.request().url()).pathname.split('/conversations/')[1].split('/')[0]
    const index = Number(id.split('-')[1]) || 1
    return json(route, { conversation_id: id, messages: [
      { id: `question-${index}`, role: 'user', content: state.records[index - 1]?.conversation_title || '问题', created_at: new Date().toISOString() },
      { id: `message-${index}`, role: 'assistant', content: '原回答', created_at: new Date().toISOString(), citations: [{ document_id: 'doc-config', document_name: '知识库配置指南.md', chunk_id: 'chunk-1', header_path: '3.2 分段策略', chunk_content: '按标题与段落组织正文，避免将配置项及其说明拆到不同片段。', relevance_score: .91 }, { document_id: 'doc-parser', document_name: '文档处理说明.pdf', chunk_id: 'chunk-2', page_number: 12, chunk_content: '调整分段配置后，使用固定的问题集检查引用完整性，核验命中内容与答案依据。', relevance_score: .88 }] },
    ] })
  })
  return state
}
async function openInbox(page: Page) {
  await page.goto('/knowledge/feedback', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '反馈质检', exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.locator('[data-feedback-item]')).toHaveCount(12)
  await expect(page.getByRole('button', { name: /知识库配置指南/ })).toBeVisible()
  await page.evaluate(() => document.fonts.ready)
}
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
}

test('feedback inbox preserves filters, persists archive and binds delayed regression results', async ({ page }) => {
  const state = await fixture(page)
  await page.setViewportSize({ width: 1600, height: 1000 })
  await openInbox(page)
  const reader = page.locator('[data-feedback-reader]')
  await page.screenshot({ path: path.join(evidence, 'desktop.png') })
  await page.getByRole('combobox', { name: '反馈处理状态' }).click()
  await page.getByRole('option', { name: /待分析/ }).click()
  await expect(page.locator('[data-feedback-item]')).toHaveCount(9)
  await page.getByRole('combobox', { name: '反馈评分' }).click()
  await page.getByRole('option', { name: '5 / 5 分' }).click()
  await expect(page.locator('[data-feedback-item]')).toHaveCount(2)
  await page.getByRole('button', { name: '清除筛选', exact: true }).click()
  await page.getByRole('button', { name: '更多反馈筛选' }).click()
  await page.getByRole('combobox', { name: '反馈来源' }).click()
  await page.getByRole('option', { name: 'API 接口', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-feedback-item]')).toHaveCount(6)
  await page.getByRole('button', { name: '清除筛选', exact: true }).click()
  await page.getByRole('searchbox', { name: '搜索反馈' }).fill('不存在的反馈')
  await expect(page.locator('[data-feedback-item]')).toHaveCount(0)
  await page.getByRole('button', { name: '清除筛选', exact: true }).first().click()
  state.failArchive = true
  await page.getByRole('button', { name: '归档反馈', exact: true }).click()
  await expect(reader.getByRole('alert')).toContainText('归档失败')
  await page.screenshot({ path: path.join(evidence, 'archive-error.png') })
  await expect(page.locator('[data-feedback-item][aria-current="true"]')).toHaveAttribute('data-feedback-item', 'feedback-1')
  state.failArchive = false
  await page.getByRole('button', { name: '归档反馈', exact: true }).click()
  await expect(page.getByRole('button', { name: '取消归档', exact: true })).toBeEnabled()
  await page.reload()
  await expect(page.getByRole('button', { name: '取消归档', exact: true })).toBeVisible()
  let finish!: () => void
  state.holdCase = new Promise(resolve => { finish = resolve })
  await page.getByRole('button', { name: '创建回归用例', exact: true }).click()
  await expect.poll(() => state.writes.includes('case:feedback-1')).toBe(true)
  await page.getByRole('button', { name: '下一条反馈' }).click()
  finish()
  await expect(reader.getByRole('link', { name: '查看回归用例' })).toHaveCount(0)
  await page.getByRole('button', { name: '上一条反馈' }).click()
  await expect(reader.getByRole('link', { name: '查看回归用例' })).toBeVisible()
  expect(state.writes.filter(item => item.startsWith('case:'))).toHaveLength(1)
  await page.getByRole('button', { name: '反哺候选', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('困难负样本')
  await page.getByRole('dialog').getByRole('button', { name: /规则候选/ }).click()
  await expect(page.getByRole('dialog')).toContainText('分段')
  await page.screenshot({ path: path.join(evidence, 'candidates.png') })
  await page.keyboard.press('Escape')
  await noOverflow(page)
})

test('feedback inbox handles empty and error states, long content, phone navigation and theme surfaces', async ({ page }) => {
  const state = await fixture(page)
  await openInbox(page)
  await page.setViewportSize({ width: 1280, height: 800 })
  await noOverflow(page)
  await expect(page.getByRole('button', { name: '归档反馈', exact: true })).toBeVisible()
  await page.screenshot({ path: path.join(evidence, 'laptop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await expect(page.locator('[data-feedback-item]')).toHaveCount(12)
  await expect(page.locator('[data-feedback-queue]')).toBeVisible()
  await expect(page.locator('[data-feedback-reader]')).toBeHidden()
  await noOverflow(page)
  await page.screenshot({ path: path.join(evidence, 'phone-queue.png') })
  await page.locator('[data-feedback-item="feedback-1"]').click()
  await expect(page.getByRole('button', { name: '返回反馈队列' })).toBeVisible()
  await expect(page.getByRole('button', { name: '归档反馈', exact: true })).toBeVisible()
  await noOverflow(page)
  await page.screenshot({ path: path.join(evidence, 'phone-detail.png') })
  await page.getByRole('button', { name: '返回反馈队列' }).click()
  await expect(page.locator('[data-feedback-item="feedback-1"]')).toBeFocused()
  await page.setViewportSize({ width: 1600, height: 1000 })
  state.records[0].message_content += '\n\n' + '需要核对很长的原始回答。'.repeat(500)
  await page.getByRole('button', { name: '刷新反馈' }).click()
  const content = page.getByLabel('反馈内容', { exact: true })
  await expect(content).toContainText('需要核对很长的原始回答。')
  expect(await content.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true)
  await expect(page.getByRole('button', { name: '归档反馈', exact: true })).toBeInViewport()
  state.failList = true
  await page.getByRole('button', { name: '刷新反馈' }).click()
  await expect(page.getByRole('alert').filter({ hasText: '反馈加载失败' })).toBeVisible()
  await expect(page.locator('[data-feedback-reader]')).toBeVisible()
  state.failList = false; state.records = []
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect(page.locator('[data-feedback-item]')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '暂无反馈', exact: true })).toBeVisible()
  await page.screenshot({ path: path.join(evidence, 'empty.png') })
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.evaluate(() => { localStorage.setItem('theme', 'dark') })
  await page.reload()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await expect(page.getByRole('heading', { name: '暂无反馈', exact: true })).toBeVisible()
  await page.screenshot({ path: path.join(evidence, 'dark-empty.png') })
})
