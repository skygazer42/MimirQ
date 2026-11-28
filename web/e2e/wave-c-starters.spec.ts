import { expect, test, type Page } from '@playwright/test'
import type { FeedbackLoopCandidatesResponse } from '../types/feedback'
import type { KGManualImportResponse } from '../types/knowledge-graph'
import type { DocumentParsedContentResponse } from '../types/backend'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

const conversation = {
  id: '11111111-1111-4111-8111-111111111111',
  title: '质量复核问答',
  message_count: 2,
  created_at: '2026-11-24T00:00:00Z',
  updated_at: '2026-11-24T00:00:00Z',
}

async function fixture(page: Page) {
  await installCommonApiMocks(page, { uploaded: false })
  const state = {
    conversations: [] as (typeof conversation)[],
    evaluable: true,
    failQueue: false,
    graphImported: false,
  }
  await page.addInitScript(() => {
    localStorage.setItem('theme', 'light')
    localStorage.setItem('mimirq.surfaceTheme', 'ocean')
    localStorage.removeItem('mimirq.themeColor')
  })
  await page.route('**/api/v1/**', (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === '/api/v1/chat/conversations')
      return route.fulfill({
        json: {
          items: state.conversations,
          total: state.conversations.length,
          returned: state.conversations.length,
          has_more: false,
          next_skip: null,
        },
      })
    if (/^\/api\/v1\/documents\/?$/.test(path))
      return route.fulfill(
        state.failQueue ? { status: 503, json: { detail: '队列暂不可用' } } : { json: { items: [], total: 0 } },
      )
    if (path === '/api/v1/feedback/messages/enriched') return route.fulfill({ json: { items: [], total: 0 } })
    if (path === '/api/v1/feedback/loop/candidates')
      return route.fulfill({
        json: {
          schema: 'test',
          summary: {
            feedback_total: 0,
            negative_feedback_total: 0,
            hard_negative_records: 0,
            training_triples: 0,
            eval_case_candidates: 0,
            rules_glossary_candidates: 0,
            rules_pattern_candidates: 0,
            rules_intent_candidates: 0,
          },
          hard_negative_records: [],
          training_triples: [],
          eval_case_candidates: [],
          rules_suggestions: {
            schema: 'test',
            ruleset: null,
            glossary_suggestions: [],
            pattern_suggestions: [],
            intent_suggestions: [],
          },
        } satisfies FeedbackLoopCandidatesResponse,
      })
    if (path === '/api/v1/meta/details') return route.fulfill({ json: { features: { kg_enabled: true } } })
    if (path === '/api/v1/kg/graph')
      return route.fulfill({
        json: {
          nodes: state.graphImported
            ? [{ id: 'imported-entity', label: '导入实体', meta: { kind: 'entity', type: '文档' } }]
            : [],
          links: [],
        },
      })
    if (path === '/api/v1/kg/imports/preview' || path === '/api/v1/kg/imports') {
      if (path === '/api/v1/kg/imports') state.graphImported = true
      return route.fulfill({
        json: {
          import_id: 'wave-c-import',
          pipeline_hash: 'test',
          name: 'Wave C',
          valid: true,
          stats: { entities: 1, relations: 0, events: 0, chunks: 0, aliases: 0, warnings: 0 },
          issues: [],
          message: '已导入',
        } satisfies KGManualImportResponse,
      })
    }
    if (path === '/api/v1/kg/stats')
      return route.fulfill({ json: { entities: 0, events: 0, links: 0, entity_types: [] } })
    if (path === '/api/v1/evaluations/ragas/runs') return route.fulfill({ json: { items: [], total: 0 } })
    if (path.endsWith('/conversation-readiness'))
      return route.fulfill({
        json: {
          total: state.conversations.length,
          items: state.conversations.map(({ id }) => ({
            conversation_id: id,
            assistant_turns: 1,
            evaluable_turns: state.evaluable ? 1 : 0,
            citations_count: state.evaluable ? 1 : 0,
            is_evaluable: state.evaluable,
          })),
        },
      })
    return route.fallback()
  })
  return state
}

async function shot(page: Page, name: string) {
  await page.evaluate(() => document.fonts.ready)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), animations: 'disabled' })
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`history empty archive has one primary starter at ${viewport.width}`, async ({ page }) => {
    await fixture(page)
    await page.setViewportSize(viewport)
    await page.goto('/history', { waitUntil: 'domcontentloaded' })
    const title = page.getByRole('heading', { name: '暂无问答记录', exact: true })
    await expect(title).toBeVisible({ timeout: 60000 })
    const card = title.locator('..')
    await expect(card).toHaveCSS('border-top-width', '1px')
    await expect(card.getByRole('link', { name: '新建对话', exact: true })).toBeInViewport({ ratio: 1 })
    await expect(card.getByRole('link', { name: '前往知识库', exact: true })).toHaveAttribute('href', '/knowledge')
    await expect(page.locator('[data-history-sidebar]')).toBeHidden()
    const primary = await card
      .getByRole('link', { name: '新建对话', exact: true })
      .evaluate((element) => getComputedStyle(element).backgroundColor)
    const header = await page
      .locator('main header')
      .getByRole('link', { name: '新建对话', exact: true })
      .evaluate((element) => getComputedStyle(element).backgroundColor)
    expect(header).not.toBe(primary)
    await shot(page, 'history-empty')
  })

  test(`quarantine empty queue keeps scope and error recovery distinct at ${viewport.width}`, async ({ page }) => {
    const state = await fixture(page)
    await page.setViewportSize(viewport)
    await page.goto('/knowledge/quarantine', { waitUntil: 'domcontentloaded' })
    const card = page.getByRole('heading', { name: '当前没有待复核文档', exact: true }).locator('..')
    await expect(card).toBeVisible({ timeout: 60000 })
    await expect(card.getByRole('link', { name: '查看知识库', exact: true })).toHaveAttribute('href', '/knowledge')
    await expect(card.getByRole('link', { name: '管理治理配置', exact: true })).toHaveAttribute(
      'href',
      '/data-governance/profiles',
    )
    await expect(page.getByRole('button', { name: '导出', exact: true })).toBeDisabled()
    await expect(page.locator('main table')).toHaveCount(0)
    await expect(page.getByRole('combobox', { name: '筛选数据集', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '下一页', exact: true })).toHaveCount(0)
    await shot(page, 'quarantine-empty')
    await page.goto('/knowledge/quarantine?datasetId=starter-dataset', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: '没有符合条件的文档', exact: true })).toBeVisible({ timeout: 60000 })
    await expect(page.getByRole('combobox', { name: '筛选数据集', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '清除筛选', exact: true }).first()).toBeVisible()
    await shot(page, 'quarantine-scoped-empty')
    state.failQueue = true
    await page.goto('/knowledge/quarantine', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: '隔离队列加载失败', exact: true })).toBeVisible({ timeout: 60000 })
    await expect(page.getByRole('button', { name: '重新加载', exact: true })).toBeEnabled()
    await expect(page.getByText('所有文档均已通过质量门禁。', { exact: false })).toHaveCount(0)
  })

  test(`quarantine populated table retains review, tuning and export at ${viewport.width}`, async ({ page }) => {
    await fixture(page)
    const document = {
      id: 'wave-c-document',
      filename: '待复核资料.pdf',
      dataset_id: 'starter-dataset',
      status: 'quarantined',
      file_size: 1024,
      updated_at: '2026-11-24T00:00:00Z',
      metadata: {},
      governance: { drop_reasons: { outline_only: 1 } },
    }
    await page.route(/\/api\/v1\/documents\/?\?/, (route) => {
      const quarantined = new URL(route.request().url()).searchParams.get('status') === 'quarantined'
      return route.fulfill({ json: { items: quarantined ? [document] : [], total: quarantined ? 1 : 0 } })
    })
    await page.route('**/api/v1/documents/wave-c-document/parsed-content**', (route) =>
      route.fulfill({
        json: {
          document_id: document.id,
          available: true,
          original_markdown_content: '待复核原文',
          markdown_content: '',
          markdown_truncated: false,
          original_markdown_truncated: false,
          max_chars: 1400,
        } satisfies DocumentParsedContentResponse,
      }),
    )
    await page.setViewportSize(viewport)
    await page.goto('/knowledge/quarantine', { waitUntil: 'domcontentloaded' })
    const table = page.getByRole('region', { name: '隔离文档列表', exact: true })
    await expect(table).toContainText(document.filename, { timeout: 60000 })
    await expect(table).toHaveCSS('border-top-width', '1px')
    await expect(table).toHaveCSS('border-top-left-radius', '10px')
    await page.getByRole('button', { name: `复核 ${document.filename}`, exact: true }).click()
    await expect(page.getByText('待复核原文', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '放行并重试', exact: true })).toBeEnabled()
    await expect(page.getByRole('button', { name: '重试', exact: true })).toBeEnabled()
    await page.getByRole('button', { name: '调参', exact: true }).click()
    await expect(page.getByRole('dialog', { name: '调参回放', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    const downloading = page.waitForEvent('download')
    await page.getByRole('button', { name: '导出', exact: true }).click()
    expect((await downloading).suggestedFilename()).toBe('quarantine-documents.json')
    if (viewport.width > 1000) {
      await page.setViewportSize({ width: 1920, height: 1080 })
      expect((await table.boundingBox())!.width).toBeLessThanOrEqual(1384)
    }
    await shot(page, 'quarantine-populated')
    await page.getByRole('searchbox', { name: '搜索隔离文档', exact: true }).fill('没有匹配')
    await expect(page.getByRole('heading', { name: '没有符合条件的文档', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '清除筛选', exact: true }).first()).toBeVisible()
  })

  test(`feedback empty inbox opens the existing candidate dialog at ${viewport.width}`, async ({ page }) => {
    await fixture(page)
    await page.setViewportSize(viewport)
    await page.goto('/knowledge/feedback', { waitUntil: 'domcontentloaded' })
    const card = page.getByRole('heading', { name: '暂无反馈记录', exact: true }).locator('..')
    await expect(card).toBeVisible({ timeout: 60000 })
    await expect(card.getByRole('link', { name: '前往知识问答', exact: true })).toHaveAttribute('href', '/')
    await expect(page.locator('[data-feedback-queue], [data-feedback-reader]')).toHaveCount(0)
    await expect(page.getByRole('button', { name: '下一页反馈', exact: true })).toHaveCount(0)
    await expect(card.getByRole('button', { name: '反哺候选', exact: true })).toBeInViewport({ ratio: 1 })
    await shot(page, 'feedback-empty')
    await card.getByRole('button', { name: '反哺候选', exact: true }).click()
    await expect(page.getByRole('dialog', { name: '反哺候选', exact: true })).toContainText('暂无困难负样本')
    await page.keyboard.press('Escape')
    await expect(card.getByRole('button', { name: '反哺候选', exact: true })).toBeFocused()
  })

  test(`graph empty canvas omits duplicate and inapplicable controls at ${viewport.width}`, async ({ page }) => {
    await fixture(page)
    await page.setViewportSize(viewport)
    await page.goto('/graph', { waitUntil: 'domcontentloaded' })
    const card = page.getByRole('heading', { name: '选择或导入知识图谱', exact: true }).locator('..')
    await expect(card).toBeVisible({ timeout: 60000 })
    await expect(card.getByRole('button', { name: '选择图谱', exact: true })).toBeInViewport({ ratio: 1 })
    await expect(
      page.locator('[data-graph-directory]').getByRole('button', { name: '选择图谱', exact: true }),
    ).toHaveCount(0)
    await expect(page.getByRole('group', { name: '图谱画布工具', exact: true })).toHaveCount(0)
    await shot(page, 'graph-empty')
    await card.getByRole('button', { name: '选择图谱', exact: true }).click()
    await expect(page.getByRole('dialog', { name: '选择图谱范围', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(card.getByRole('button', { name: '选择图谱', exact: true })).toBeFocused()
    const chooser = page.waitForEvent('filechooser')
    await card.getByRole('button', { name: '导入 KG JSON / JSONL', exact: true }).click()
    const fileChooser = await chooser
    expect(await fileChooser.element().getAttribute('accept')).toContain('.jsonl')
    await fileChooser.setFiles({
      name: 'wave-c.jsonl',
      mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify({ kind: 'entity', name: '导入实体', type: '文档' })),
    })
    await expect(page.locator('[data-directory-node="imported-entity"]')).toBeVisible()
    if (viewport.width < 1000) await page.getByRole('button', { name: '关系图谱', exact: true }).click()
    await expect(page.getByRole('group', { name: '图谱画布工具', exact: true })).toBeVisible()
  })

  test(`evaluation starter and compressed header retain native parameters at ${viewport.width}`, async ({ page }) => {
    const state = await fixture(page)
    await page.setViewportSize(viewport)
    await page.goto('/evaluations', { waitUntil: 'domcontentloaded' })
    const title = page.getByRole('heading', { name: '选择对话以开始评测', exact: true })
    await expect(title).toBeVisible({ timeout: 60000 })
    await expect(page.locator('main header').getByRole('tablist', { name: '评测类型', exact: true })).toBeVisible()
    await expect(page.getByRole('table', { name: '逐轮评分矩阵', exact: true })).toHaveCount(0)
    await expect(page.getByRole('region', { name: '样本阅读区', exact: true })).toHaveCount(0)
    await expect(title.locator('..').getByRole('button', { name: '选择对话', exact: true })).toBeInViewport({
      ratio: 1,
    })
    await shot(page, 'evaluations-no-conversation')
    await title.locator('..').getByRole('button', { name: '选择对话', exact: true }).click()
    await expect(page.getByRole('dialog', { name: '选择对话', exact: true })).toBeVisible()
    await page.keyboard.press('Escape')
    state.conversations = [conversation]
    await page.reload()
    const card = page.getByRole('heading', { name: '尚未运行对话评测', exact: true }).locator('..')
    await expect(card).toBeVisible({ timeout: 60000 })
    await expect(card.getByRole('button', { name: '开始评测', exact: true })).toBeEnabled()
    const summary = page.getByRole('button', { name: '评测参数', exact: true }).filter({ hasText: '2 项指标' })
    await expect(summary).toContainText('最近 20 轮')
    await summary.click()
    const dialog = page.getByRole('dialog', { name: '评测参数', exact: true })
    await dialog.getByRole('spinbutton', { name: '最近轮次', exact: true }).fill('35')
    await dialog.getByRole('button', { name: '完成', exact: true }).click()
    await expect(summary).toBeFocused()
    await expect(summary).toContainText('最近 35 轮')
    if (viewport.width > 1000) {
      const header = await page.locator('main header').boundingBox()
      const picker = await page.getByRole('button', { name: '质量复核问答', exact: true }).boundingBox()
      expect(picker!.y).toBeLessThanOrEqual(header!.y + header!.height + 20)
    }
    await shot(page, 'evaluations-no-runs')
    state.evaluable = false
    await page.reload()
    await expect(card).toBeVisible({ timeout: 60000 })
    await expect(page.getByRole('button', { name: '开始评测', exact: true })).toBeDisabled()
    await expect(card.getByText('这条对话没有引用上下文', { exact: true })).toBeVisible()
    await expect(page.getByRole('table', { name: '逐轮评分矩阵', exact: true })).toHaveCount(0)
  })
}
