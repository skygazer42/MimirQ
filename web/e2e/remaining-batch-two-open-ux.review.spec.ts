import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { batchTwoFixture } from './remaining-batch-two.helpers'
import { realDatasetFixture } from './remaining-pages.helpers'

const root = path.resolve(__dirname, '../../artifacts/rebrand/remaining-pages-2026-10-27/open-ux-batch-two')
fs.mkdirSync(root, { recursive: true })
test.use({ actionTimeout: 10_000 })

async function snapshot(page: Page, name: string) {
  await page.screenshot({ path: path.join(root, `${name}.png`), animations: 'disabled' })
  await page.screenshot({ path: path.join(root, `${name}-full.png`), fullPage: true, animations: 'disabled' })
  fs.writeFileSync(path.join(root, `${name}.txt`), await page.locator('body').ariaSnapshot())
  fs.writeFileSync(path.join(root, `${name}.metadata.json`), JSON.stringify({ url: page.url(), viewport: page.viewportSize(), captured_at: new Date().toISOString() }, null, 2))
}

test('independent initial rendered surfaces', async ({ browser }) => {
  test.setTimeout(420_000)
  for (const [device, viewport] of [['desktop', { width: 1600, height: 1000 }], ['mobile', { width: 390, height: 844 }]] as const) {
    for (const [surface, url] of [['ingestion', '/knowledge/ingestion?mode=execution-monitor'], ['common-lines', '/data-governance/common-lines'], ['industry-rules', '/governance/industry-rules']] as const) {
      const context = await browser.newContext({ viewport })
      const page = await context.newPage()
      await page.route('**/api/v1/**', async route => {
        if (!['GET', 'HEAD', 'OPTIONS'].includes(route.request().method())) return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '独立走查未覆盖的写入已隔离' }) })
        return route.continue()
      })
      await batchTwoFixture(page)
      await page.setViewportSize(viewport)
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90_000 })
      await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible({ timeout: 90_000 })
      await snapshot(page, `initial-${device}-${surface}`)
      await context.close()
    }
  }
})

test('independent chosen task first actions', async ({ browser }) => {
  test.setTimeout(420_000)
  for (const [device, viewport] of [['desktop', { width: 1600, height: 1000 }], ['mobile', { width: 390, height: 844 }]] as const) {
    const context = await browser.newContext({ viewport })
    const page = await context.newPage()
    await page.route('**/api/v1/**', async route => {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(route.request().method())) return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '独立走查未覆盖的写入已隔离' }) })
      return route.continue()
    })
    await batchTwoFixture(page)
    await page.setViewportSize(viewport)
    await page.goto('/knowledge/ingestion?mode=execution-monitor', { waitUntil: 'domcontentloaded', timeout: 90_000 })
    await expect(page.getByRole('heading', { name: '入库执行监控', exact: true })).toBeVisible({ timeout: 90_000 })
    await page.getByRole('button', { name: '失败 6', exact: true }).click()
    await snapshot(page, `task-${device}-failed-filter`)
    await page.getByRole('button', { name: /^查看任务 / }).first().click()
    await snapshot(page, `task-${device}-failed-detail`)

    await page.goto('/data-governance/common-lines', { waitUntil: 'domcontentloaded', timeout: 90_000 })
    await expect(page.getByRole('heading', { name: '重复内容规则', exact: true })).toBeVisible({ timeout: 90_000 })
    await page.getByRole('button', { name: '扫描重复内容', exact: true }).click()
    await snapshot(page, `task-${device}-after-scan-action`)
    if (device === 'mobile') await page.getByRole('button', { name: '规则与样本', exact: true }).click()
    await expect(page.getByText('版权所有，未经许可不得转载', { exact: true })).toBeVisible()
    await snapshot(page, `task-${device}-repeated-candidates`)

    await page.goto('/governance/industry-rules', { waitUntil: 'domcontentloaded', timeout: 90_000 })
    await expect(page.getByRole('heading', { name: '行业规则', exact: true })).toBeVisible({ timeout: 90_000 })
    await page.getByRole('button', { name: '新增术语', exact: true }).click()
    await snapshot(page, `task-${device}-new-term`)
    await context.close()
  }
})

test('independent repeated-content and glossary outcomes', async ({ browser }) => {
  test.setTimeout(300_000)
  for (const [device, viewport] of [['desktop', { width: 1600, height: 1000 }], ['mobile', { width: 390, height: 844 }]] as const) {
    const context = await browser.newContext({ viewport })
    const page = await context.newPage()
    await page.route('**/api/v1/**', async route => {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(route.request().method())) return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '独立走查未覆盖的写入已隔离' }) })
      return route.continue()
    })
    const state = await batchTwoFixture(page)
    await page.setViewportSize(viewport)
    await page.goto('/data-governance/common-lines', { waitUntil: 'domcontentloaded', timeout: 90_000 })
    await expect(page.getByRole('heading', { name: '重复内容规则', exact: true })).toBeVisible({ timeout: 90_000 })
    await page.getByRole('button', { name: '扫描重复内容', exact: true }).click()
    await snapshot(page, `outcome-${device}-scan-current-panel`)
    if (device === 'mobile') await page.getByRole('button', { name: '规则与样本', exact: true }).click()
    await expect(page.getByText('版权所有，未经许可不得转载', { exact: true })).toBeVisible()
    await page.getByRole('checkbox', { name: '选择重复行 版权所有，未经许可不得转载', exact: true }).check()
    state.failSave = true
    await page.getByRole('button', { name: /^写入配置/ }).click()
    await expect(page.getByRole('alert').filter({ hasText: '配置保存失败' })).toBeVisible()
    await snapshot(page, `outcome-${device}-common-save-failed`)
    state.failSave = false
    await page.getByRole('button', { name: /^写入配置/ }).click()
    await expect.poll(() => state.writes.filter(write => write.path.endsWith('/ui-profile')).length).toBe(2)
    await expect(page.getByText('已写入治理配置：新增 1 条规则', { exact: true })).toBeVisible()
    await snapshot(page, `outcome-${device}-common-saved`)
    await page.goto('/data-governance/common-lines', { waitUntil: 'domcontentloaded', timeout: 90_000 })
    await expect(page.getByRole('heading', { name: '重复内容规则', exact: true })).toBeVisible({ timeout: 90_000 })
    await expect(page.getByRole('button', { name: '产品内容清洗 ui-profile', exact: true })).toBeVisible()
    if (device === 'mobile') await page.getByRole('button', { name: '规则与样本', exact: true }).click()
    await page.getByRole('tab', { name: '已保存规则', exact: true }).click()
    await snapshot(page, `outcome-${device}-common-saved-rules`)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: '重复内容规则', exact: true })).toBeVisible({ timeout: 90_000 })
    if (device === 'mobile') await page.getByRole('button', { name: '规则与样本', exact: true }).click()
    await page.getByRole('tab', { name: '已保存规则', exact: true }).click()
    await snapshot(page, `outcome-${device}-common-reread`)

    await page.goto('/governance/industry-rules', { waitUntil: 'domcontentloaded', timeout: 90_000 })
    await expect(page.getByRole('heading', { name: '行业规则', exact: true })).toBeVisible({ timeout: 90_000 })
    await page.getByRole('button', { name: '新增术语', exact: true }).click()
    await page.getByRole('textbox', { name: '术语', exact: true }).fill('文档治理')
    await page.getByRole('textbox', { name: '别名，逗号分隔', exact: true }).fill('内容治理, 知识清洗')
    await page.getByRole('button', { name: '完成编辑', exact: true }).click()
    await expect(page.getByRole('cell', { name: '文档治理', exact: true })).toBeVisible()
    state.failSave = true
    await page.getByRole('button', { name: '保存术语', exact: true }).click()
    await expect(page.getByRole('alert').filter({ hasText: '规则保存失败' })).toBeVisible()
    await snapshot(page, `outcome-${device}-glossary-save-failed`)
    state.failSave = false
    await page.getByRole('button', { name: '保存术语', exact: true }).click()
    await expect.poll(() => state.writes.filter(write => write.path.includes('/industry-rules/rulesets/')).length).toBe(2)
    await snapshot(page, `outcome-${device}-glossary-saved`)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('cell', { name: '文档治理', exact: true })).toBeVisible({ timeout: 90_000 })
    await snapshot(page, `outcome-${device}-glossary-reread`)
    await page.getByRole('button', { name: '查询预览', exact: true }).click()
    await snapshot(page, `outcome-${device}-query-preview`)
    fs.writeFileSync(path.join(root, `outcome-${device}-fixture-writes.json`), JSON.stringify(state.writes, null, 2))
    await context.close()
  }
})

test('independent draft and live-query risk probes', async ({ browser }) => {
  test.setTimeout(240_000)
  for (const [device, viewport] of [['desktop', { width: 1600, height: 1000 }], ['mobile', { width: 390, height: 844 }]] as const) {
    const context = await browser.newContext({ viewport })
    const page = await context.newPage()
    await page.route('**/api/v1/**', async route => {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(route.request().method())) return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '独立走查未覆盖的写入已隔离' }) })
      return route.continue()
    })
    const state = await batchTwoFixture(page)
    await page.setViewportSize(viewport)
    await page.goto('/governance/industry-rules', { waitUntil: 'domcontentloaded', timeout: 90_000 })
    await expect(page.getByRole('heading', { name: '行业规则', exact: true })).toBeVisible({ timeout: 90_000 })
    await page.getByRole('button', { name: '新增术语', exact: true }).click()
    await page.getByRole('textbox', { name: '术语', exact: true }).fill('知识编目')
    await page.getByRole('textbox', { name: '别名，逗号分隔', exact: true }).fill('内容目录, 文档索引')
    await page.getByRole('button', { name: '完成编辑', exact: true }).click()
    await page.getByRole('tab', { name: '问题模式 1', exact: true }).click()
    await page.getByRole('tab', { name: '术语 3', exact: true }).click()
    await expect(page.getByRole('cell', { name: '知识编目', exact: true })).toBeVisible()
    await snapshot(page, `risk-${device}-draft-tab-return`)
    await page.getByRole('button', { name: '查询预览', exact: true }).click()
    const query = page.getByRole('textbox', { name: '输入问题', exact: true })
    await query.fill('SSO 无法连接')
    await expect(page.getByText('已补全：SSO 无法连接', { exact: true })).toBeVisible()
    await snapshot(page, `risk-${device}-query-result`)
    let releaseOld: () => void = () => {}
    state.previewGate = new Promise<void>(resolve => { releaseOld = resolve })
    const oldRequest = page.waitForRequest(request => request.url().includes('/preview-rewrite') && request.postDataJSON().query === '旧问题')
    await query.fill('旧问题')
    await oldRequest
    await snapshot(page, `risk-${device}-query-pending`)
    await query.fill('新的SSO问题')
    await expect(page.getByText('已补全：新的SSO问题', { exact: true })).toBeVisible()
    const oldResponse = page.waitForResponse(response => response.url().includes('/preview-rewrite') && response.request().postDataJSON().query === '旧问题')
    releaseOld()
    await oldResponse
    await expect(page.getByText('已补全：新的SSO问题', { exact: true })).toBeVisible()
    await snapshot(page, `risk-${device}-late-old-response`)
    await query.fill('')
    await expect(page.getByText('输入问题后查看改写结果', { exact: true })).toBeVisible()
    await expect(page.getByText('已补全：新的SSO问题', { exact: true })).toHaveCount(0)
    await snapshot(page, `risk-${device}-query-cleared`)
    await page.getByRole('button', { name: '关闭', exact: true }).click()
    await page.getByRole('tab', { name: '问题模式 1', exact: true }).click()
    await snapshot(page, `risk-${device}-pattern-inspection`)
    await context.close()
  }
})

test('independent write-result recheck and narrow table discovery', async ({ browser }) => {
  test.setTimeout(180_000)
  for (const [device, viewport] of [['desktop', { width: 1600, height: 1000 }], ['mobile', { width: 390, height: 844 }]] as const) {
    const context = await browser.newContext({ viewport })
    const page = await context.newPage()
    await page.route('**/api/v1/**', async route => {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(route.request().method())) return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '独立走查未覆盖的写入已隔离' }) })
      return route.continue()
    })
    await batchTwoFixture(page)
    await page.setViewportSize(viewport)
    await page.goto('/data-governance/common-lines', { waitUntil: 'domcontentloaded', timeout: 90_000 })
    await expect(page.getByRole('heading', { name: '重复内容规则', exact: true })).toBeVisible({ timeout: 90_000 })
    await page.getByRole('button', { name: '扫描重复内容', exact: true }).click()
    await page.getByRole('checkbox', { name: '选择重复行 版权所有，未经许可不得转载', exact: true }).check()
    await page.getByRole('button', { name: /^写入配置/ }).click()
    await expect(page.getByText('已写入治理配置：新增 1 条规则', { exact: true })).toBeVisible()
    await expect(page).toHaveURL(/\/data-governance\/common-lines$/)
    await expect(page.getByRole('tab', { name: '已保存规则', exact: true })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('cell').filter({ hasText: '版权所有，未经许可不得转载' })).toBeVisible()
    if (device === 'mobile') {
      await page.getByRole('button', { name: '治理配置', exact: true }).click()
      await expect(page.getByRole('button', { name: '产品内容清洗 ui-profile', exact: true })).toHaveAttribute('aria-pressed', 'true')
      await page.getByRole('button', { name: '规则与样本', exact: true }).click()
    } else {
      await expect(page.getByRole('button', { name: '产品内容清洗 ui-profile', exact: true })).toHaveAttribute('aria-pressed', 'true')
    }
    await snapshot(page, `recheck-${device}-common-success-in-place`)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: '重复内容规则', exact: true })).toBeVisible({ timeout: 90_000 })
    if (device === 'mobile') await page.getByRole('button', { name: '规则与样本', exact: true }).click()
    await page.getByRole('tab', { name: '已保存规则', exact: true }).click()
    await expect(page.getByRole('cell').filter({ hasText: '版权所有，未经许可不得转载' })).toBeVisible()
    await snapshot(page, `recheck-${device}-common-refresh-readback`)
    await page.goto('/governance/industry-rules', { waitUntil: 'domcontentloaded', timeout: 90_000 })
    await expect(page.getByRole('heading', { name: '行业规则', exact: true })).toBeVisible({ timeout: 90_000 })
    await expect(page.getByRole('cell', { name: '单点登录', exact: true })).toBeVisible()
    if (device === 'mobile') {
      await expect(page.getByRole('button', { name: '编辑', exact: true }).first()).toBeInViewport()
      await expect(page.getByRole('cell', { name: '单点登录', exact: true })).toBeInViewport()
      await expect(page.getByText('左右滑动查看完整字段', { exact: true })).toBeVisible()
      await snapshot(page, 'recheck-mobile-row-actions-in-place')
      await page.getByRole('button', { name: '编辑', exact: true }).first().click()
      await expect(page.getByRole('textbox', { name: '术语', exact: true })).toHaveValue('单点登录')
      await snapshot(page, 'recheck-mobile-direct-edit')
      await page.getByRole('button', { name: '取消', exact: true }).click()
      await page.getByRole('table').hover()
      await page.mouse.wheel(1000, 0)
      await expect(page.getByRole('button', { name: '编辑', exact: true }).first()).toBeInViewport()
      await snapshot(page, 'recheck-mobile-actions-after-scroll')
      await page.getByRole('button', { name: '编辑', exact: true }).first().click()
      await expect(page.getByRole('dialog', { name: '编辑术语', exact: true })).toBeVisible()
      await expect(page.getByRole('textbox', { name: '术语', exact: true })).toHaveValue('单点登录')
      await snapshot(page, 'recheck-mobile-edit-after-horizontal-scroll')
      await page.getByRole('button', { name: '取消', exact: true }).click()
    }
    await context.close()
  }
})

test('independent real API read-only surfaces', async ({ browser }) => {
  test.setTimeout(300_000)
  for (const [device, viewport] of [['desktop', { width: 1600, height: 1000 }], ['mobile', { width: 390, height: 844 }]] as const) {
    const context = await browser.newContext({ viewport })
    const page = await context.newPage()
    const state = await realDatasetFixture(page)
    await page.route('**/api/v1/**', async route => {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(route.request().method())) return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '独立走查的真实 API 操作仅限读取' }) })
      return route.fallback()
    })
    await page.setViewportSize(viewport)
    await page.goto('/knowledge/ingestion?mode=execution-monitor', { waitUntil: 'domcontentloaded', timeout: 90_000 })
    await expect(page.getByRole('heading', { name: '入库执行监控', exact: true })).toBeVisible({ timeout: 90_000 })
    await page.getByRole('combobox', { name: '数据集', exact: true }).selectOption(state.dataset_id)
    await expect(page.getByRole('button', { name: '重新读取', exact: true })).toBeEnabled()
    await expect(page.getByText(/正在读取执行任务/)).toBeHidden()
    await snapshot(page, `real-${device}-dedicated-ingestion`)
    const first = page.getByRole('button', { name: /^查看任务 / }).first()
    if (await first.count()) {
      await first.click()
      await expect(page.getByRole('dialog', { name: '入库详情', exact: true })).toBeVisible()
      await snapshot(page, `real-${device}-dedicated-detail`)
    }
    await page.goto('/data-governance/common-lines', { waitUntil: 'domcontentloaded', timeout: 90_000 })
    await expect(page.getByRole('heading', { name: '重复内容规则', exact: true })).toBeVisible({ timeout: 90_000 })
    await page.getByRole('combobox', { name: '数据集', exact: true }).click()
    await page.getByRole('option', { name: state.name, exact: true }).click()
    await expect(page.getByRole('button', { name: new RegExp(state.name) }).first()).toBeVisible()
    await snapshot(page, `real-${device}-common-lines`)
    await page.goto('/governance/industry-rules', { waitUntil: 'domcontentloaded', timeout: 90_000 })
    await expect(page.getByRole('heading', { name: '行业规则', exact: true })).toBeVisible({ timeout: 90_000 })
    await expect(page.getByRole('table')).toBeVisible()
    await snapshot(page, `real-${device}-industry-rules`)
    await context.close()
  }
})
