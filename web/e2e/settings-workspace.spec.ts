import { expect, test, type Page } from '@playwright/test'
import type { BackendMetaDetails } from '@/lib/api/meta'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

const sections = [
  ['sec-status', '系统状态'],
  ['sec-models', '模型接入'],
  ['sec-flags', '功能开关'],
  ['sec-frontend', '处理偏好'],
  ['sec-navigation', '导航显示'],
  ['sec-parsers', '解析服务'],
  ['sec-rag', '检索与生成'],
  ['sec-dify', 'Dify 接入'],
  ['sec-governance', '数据治理'],
  ['sec-industry-rules', '行业规则'],
  ['sec-observability', '监控与审计'],
  ['sec-runtime', '运行控制'],
] as const

async function fixture(page: Page, theme: 'light' | 'dark' = 'light') {
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.addInitScript((theme) => {
    localStorage.setItem('theme', theme)
    localStorage.setItem('mimirq.surfaceTheme', 'ocean')
    localStorage.removeItem('mimirq.themeColor')
  }, theme)
  const state = {
    failRead: false,
    failSave: false,
    reads: 0,
    writes: [] as Record<string, unknown>[],
    saved: {
      llm: { api_key: '', api_base: '', model: '', temperature: 0.7, timeout: 60, max_retries: 1 },
      embedding: { provider: 'openai_compatible', model: '', api_base: '', api_key: '' },
      feature_flags: { kg_enabled: false },
      governance: { enabled: false, pii_anonymize: false, secrets_redact: false, quarantine_on_drop: false },
      rag: { retrieval_top_k: 5, similarity_threshold: 0.7, bm25_index_enabled: false },
      navigation: { user_visible_modules: [] },
      chat: { stream_heartbeat_sec: 10, stream_cancel_on_disconnect: true },
    },
  }
  await page.route('**/api/v1/pipeline/capabilities', (route) =>
    route.fulfill({
      json: {
        default_parser_backend: 'auto',
        default_chunk_strategy: 'langchain_recursive',
        pdf_backends: [
          { name: 'auto', available: true },
          { name: 'basic', available: true },
          { name: 'docling', available: true },
          { name: 'markitdown', available: true },
        ],
        chunk_strategies: [
          { name: 'langchain_recursive', available: true },
          { name: 'langchain_token', available: true },
          { name: 'pdf_layout', available: true },
        ],
      },
    }),
  )
  await page.route('**/api/v1/meta/details', (route) =>
    route.fulfill({
      json: {
        name: 'Ragvia API',
        api_version: 'ui95-e2e',
        build: { sha: 'ui95e2e' },
        time: '2026-11-23T00:00:00Z',
        features: {
          auth_mode: 'header',
          vector_backend: 'memory',
          kg_enabled: false,
          task_queue_enabled: false,
          embedding_cache_enabled: false,
          minio_enabled: false,
          use_langgraph_pipeline: false,
          gzip_enabled: false,
          rate_limit_enabled: false,
          cors_origins: [],
        },
        runtime: { python: '3.12', platform: 'isolated-ui-test' },
      } satisfies BackendMetaDetails,
    }),
  )
  await page.route('**/api/v1/industry-rules/rulesets', (route) =>
    route.fulfill({
      json: {
        schema: 'ragvia.industry_rules.v1',
        count: 0,
        rulesets: [],
      },
    }),
  )
  await page.route('**/api/v1/rbac/me', (route) =>
    route.fulfill({
      json: {
        tenant_id: '00000000-0000-0000-0000-000000000000',
        account_id: 'settings-review',
        role: 'owner',
        permissions: ['settings.read', 'settings.write', 'observability.read', 'audit.read'],
        is_active: true,
        is_current: true,
      },
    }),
  )
  await page.route('**/api/v1/settings', async (route) => {
    if (route.request().method() === 'GET') {
      state.reads++
      return route.fulfill({
        status: state.failRead ? 503 : 200,
        json: state.failRead ? { detail: '设置读取暂不可用' } : state.saved,
      })
    }
    if (route.request().method() === 'PUT') {
      const patch = route.request().postDataJSON() as Record<string, unknown>
      state.writes.push(patch)
      if (state.failSave) return route.fulfill({ status: 503, json: { detail: '设置保存暂不可用' } })
      state.saved = { ...state.saved, ...structuredClone(patch) }
      return route.fulfill({ json: { success: true, message: '已保存', updated_keys: Object.keys(patch) } })
    }
    return route.fallback()
  })
  return state
}

async function selectSection(page: Page, id: string, label: string) {
  const directory = page.getByRole('navigation', { name: '设置分区', exact: true })
  if (await directory.isVisible()) await directory.getByRole('button', { name: label, exact: true }).click()
  else {
    await page.getByRole('combobox', { name: '设置分区', exact: true }).click()
    await page.getByRole('option', { name: label, exact: true }).click()
  }
  await expect(page.locator(`#${id}`).getByRole('heading', { level: 2, name: label, exact: true })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`#${id}$`))
}
async function shot(page: Page, name: string) {
  await expect
    .poll(() =>
      page.evaluate(() =>
        Array.from(document.images)
          .filter((image) => image.getClientRects().length > 0 && (!image.complete || image.naturalWidth === 0))
          .map((image) => image.getAttribute('src')),
      ),
    )
    .toEqual([])
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), animations: 'disabled' })
}

test('settings keeps all sections reachable and reads saved retrieval values back', async ({ page }) => {
  test.setTimeout(180000)
  await page.setViewportSize({ width: 1440, height: 900 })
  const state = await fixture(page)
  await page.goto('/settings')
  await expect(page.getByRole('button', { name: '选择解析方式', exact: true })).toBeEnabled({ timeout: 60000 })
  await shot(page, 'preferences-desktop')
  for (const [id, label] of sections) {
    await selectSection(page, id, label)
    if (id === 'sec-status') await expect(page.getByText('ui95-e2e', { exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), label).toBe(true)
    await shot(page, id)
  }
  await selectSection(page, 'sec-models', '模型接入')
  await page
    .locator('#sec-models')
    .getByRole('button', { name: /OpenAI/ })
    .first()
    .click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await shot(page, 'model-dialog-desktop')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await selectSection(page, 'sec-rag', '检索与生成')
  const slider = page.getByRole('slider', { name: '召回 Top K', exact: true })
  await slider.focus()
  await page.keyboard.press('ArrowRight')
  await expect.poll(() => state.saved.rag.retrieval_top_k).toBe(6)
  await expect.poll(() => state.reads).toBeGreaterThan(1)
  await page.reload()
  await expect(slider).toHaveValue('6')
  await expect(page.locator('#sec-rag')).toBeVisible()
})

test('phone settings retains failed edits and retries while model dialog actions stay reachable', async ({ page }) => {
  test.setTimeout(180000)
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await fixture(page)
  state.failRead = true
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: '首次读取设置失败', exact: true })).toBeVisible({ timeout: 60000 })
  await shot(page, 'read-error-phone')
  state.failRead = false
  await page.getByRole('button', { name: '重新读取设置', exact: true }).click()
  await expect(page.getByRole('button', { name: '选择解析方式', exact: true })).toBeEnabled()
  await shot(page, 'preferences-phone')
  await selectSection(page, 'sec-rag', '检索与生成')
  state.failSave = true
  const slider = page.getByRole('slider', { name: '召回 Top K', exact: true })
  await slider.focus()
  await page.keyboard.press('ArrowRight')
  const retry = page.getByRole('button', { name: '重试保存', exact: true })
  await expect(retry).toBeVisible()
  await expect(slider).toHaveValue('6')
  expect(state.saved.rag.retrieval_top_k).toBe(5)
  await shot(page, 'save-error-phone')
  state.failSave = false
  await retry.click()
  await expect.poll(() => state.saved.rag.retrieval_top_k).toBe(6)
  await expect(retry).toHaveCount(0)
  await page.reload()
  await expect(slider).toHaveValue('6')
  await selectSection(page, 'sec-models', '模型接入')
  await page
    .locator('#sec-models')
    .getByRole('button', { name: /OpenAI/ })
    .first()
    .click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: '高级设置', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 620 })
  await dialog.evaluate(async (element) => {
    await Promise.all(element.getAnimations({ subtree: true }).map((animation) => animation.finished))
  })
  const temperature = dialog.getByRole('spinbutton', { name: 'Temperature', exact: true })
  await temperature.scrollIntoViewIfNeeded()
  await expect(dialog.getByRole('heading', { name: '配置 OpenAI', exact: true })).toBeInViewport()
  expect(
    await temperature.evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize)),
  ).toBeGreaterThanOrEqual(16)
  const save = await dialog.getByRole('button', { name: '保存配置', exact: true }).boundingBox()
  expect(save!.y).toBeGreaterThanOrEqual(0)
  expect(save!.y + save!.height).toBeLessThanOrEqual(620)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  await shot(page, 'model-dialog-phone')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})

test('settings sections remain readable in a narrow dark workspace', async ({ page }) => {
  test.setTimeout(180000)
  await page.setViewportSize({ width: 1120, height: 850 })
  await fixture(page, 'dark')
  await page.goto('/settings')
  await expect(page.getByRole('button', { name: '选择解析方式', exact: true })).toBeEnabled({ timeout: 60000 })
  await expect(page.locator('html')).toHaveClass(/dark/)
  await shot(page, 'preferences-dark')
  for (const [id, label] of sections) {
    await selectSection(page, id, label)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), label).toBe(true)
  }
  await shot(page, 'runtime-dark')
})

test('settings preserves saved values when readback fails and recovers without losing the editor', async ({ page }) => {
  const state = await fixture(page)
  await page.goto('/settings#sec-rag')
  const slider = page.getByRole('slider', { name: '召回 Top K', exact: true })
  await expect(slider).toHaveValue('5')
  state.failRead = true
  await slider.focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByRole('heading', { name: '设置同步异常', exact: true })).toBeVisible()
  await expect(page.getByRole('alert').filter({ hasText: '配置已保存，读取最新配置失败' })).toBeVisible()
  await expect(slider).toHaveValue('6')
  expect(state.saved.rag.retrieval_top_k).toBe(6)
  await shot(page, 'readback-error-desktop')
  state.failRead = false
  await page.getByRole('button', { name: '重新读取设置', exact: true }).click()
  await expect(page.getByRole('heading', { name: '设置同步异常', exact: true })).toHaveCount(0)
  await expect(slider).toHaveValue('6')
  await page.reload()
  await expect(slider).toHaveValue('6')
})

for (const view of [
  { width: 1440, height: 900, theme: 'light' as const },
  { width: 390, height: 844, theme: 'dark' as const },
]) {
  test(`unavailable pipeline options never look selected on hover at ${view.width}`, async ({ page }) => {
    await page.setViewportSize({ width: view.width, height: view.height })
    const state = await fixture(page, view.theme)
    await page.goto('/settings#sec-frontend')
    const choices = page.getByRole('radiogroup', { name: '解析方式', exact: true })
    await expect(choices).toBeVisible({ timeout: 60000 })
    await choices.locator('summary').click()
    const unavailable = choices.locator('label[data-disabled="true"]').filter({ hasText: 'PaddleOCR-VL' })
    await expect(unavailable).toBeVisible()
    await expect(unavailable.getByRole('radio')).toBeDisabled()
    await expect(unavailable).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
    await unavailable.hover()
    await expect(unavailable).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
    await expect(unavailable).toHaveCSS('cursor', 'not-allowed')
    const selected = choices.locator('label[data-selected="true"]')
    await expect(selected).not.toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
    await expect(selected.getByRole('radio')).toBeChecked()
    expect(await unavailable.locator('svg[data-platform-icon="check"]').count()).toBe(0)
    await page.screenshot({ path: test.info().outputPath('wave-d-settings-disabled.png'), animations: 'disabled' })
    expect(state.writes).toEqual([])
  })
}
