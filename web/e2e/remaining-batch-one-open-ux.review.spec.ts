import fs from 'node:fs'
import path from 'node:path'
import { test, expect, type Page } from '@playwright/test'
import { realDatasetFixture, remainingEvidence } from './remaining-pages.helpers'

const root = path.join(remainingEvidence, 'ux-open')
const suiteName = 'UX走查-入库前质量复核-1793065942462'
fs.mkdirSync(root, { recursive: true })

test.use({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
  launchOptions: { executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' },
})

async function evidence(page: Page, name: string) {
  await page.screenshot({ path: path.join(root, `${name}.png`), animations: 'disabled' })
  fs.writeFileSync(path.join(root, `${name}.txt`), `${page.url()}\n\n${await page.locator('body').innerText()}`, 'utf8')
}

test('独立 UX：手机从健康诊断找到准备资料的下一步', async ({ page }) => {
  const state = await realDatasetFixture(page)
  await page.goto(`/datasets/${state.dataset_id}/health`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '健康概览', exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText('正在读取健康概览…', { exact: true })).toBeHidden({ timeout: 60_000 })
  await evidence(page, 'mobile-isolated-health')
  await page.getByRole('button', { name: '数据画像', exact: true }).tap()
  await expect(page.getByRole('heading', { name: '数据画像', exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText('最近扫描', { exact: true })).toBeVisible({ timeout: 60_000 })
  await evidence(page, 'mobile-isolated-profile')
  await page.getByText('扫描历史', { exact: true }).tap()
  await expect(page.getByText('暂无扫描记录。启动一次深度扫描后，这里会显示快照和可对比版本。', { exact: true })).toBeVisible({ timeout: 60_000 })
  await evidence(page, 'mobile-isolated-profile-history')
  await page.getByRole('button', { name: '数据集操作', exact: true }).tap()
  await page.getByText('表格资产', { exact: true }).tap()
  await expect(page.getByRole('heading', { name: '表格资产', exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('button', { name: '去入库操作', exact: true })).toBeVisible({ timeout: 60_000 })
  await evidence(page, 'mobile-isolated-tables')
  await page.getByRole('button', { name: '去入库操作', exact: true }).tap()
  await expect(page.getByRole('heading', { name: '入库管理', exact: true })).toBeVisible({ timeout: 60_000 })
  await evidence(page, 'mobile-isolated-tables-next-step')
  await page.getByRole('button', { name: '入库配置', exact: true }).tap()
  await expect(page.getByRole('combobox', { name: '目标数据集', exact: true })).toBeVisible()
  await expect(page.getByRole('combobox', { name: '目标数据集', exact: true })).toContainText(state.name)
  await evidence(page, 'mobile-isolated-intake-config')
})

test('独立 UX：手机选择工作流节点后打开详情', async ({ page }) => {
  const state = await realDatasetFixture(page)
  await page.goto(`/datasets/${state.dataset_id}/workflow`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '工作流配置', exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText('已同步', { exact: true }).first()).toBeVisible({ timeout: 60_000 })
  await evidence(page, 'mobile-isolated-workflow')
  await page.getByText('处理流程', { exact: true }).tap()
  await page.getByRole('button', { name: '节点详情', exact: true }).tap()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByRole('dialog').getByText('未单独配置，继承默认策略', { exact: true })).toBeVisible()
  await evidence(page, 'mobile-isolated-workflow-detail')
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).tap()
  await expect(page.getByRole('dialog')).toBeHidden()
  await evidence(page, 'mobile-isolated-workflow-detail-closed')
})

test('独立 UX：手机读回复核证据集并检查创建表单', async ({ page }) => {
  const state = await realDatasetFixture(page)
  await page.goto(`/datasets/${state.dataset_id}/evidence`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '证据库', exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText(suiteName, { exact: true }).first()).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText('正在读取证据条目…', { exact: true })).toBeHidden({ timeout: 60_000 })
  await evidence(page, 'mobile-isolated-evidence')
  await page.getByRole('button', { name: '新建', exact: true }).tap()
  await expect(page.getByRole('dialog', { name: '新建证据集' })).toBeVisible()
  await page.getByRole('dialog').getByLabel('名称', { exact: true }).fill('手机复核输入-不提交')
  await page.getByRole('dialog').getByLabel('描述（可选）', { exact: true }).fill('检查窄屏表单操作，取消后不创建额外记录。')
  await evidence(page, 'mobile-isolated-evidence-dialog')
  await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).tap()
  await expect(page.getByRole('dialog')).toBeHidden()
})

test('独立 UX：手机检查数据库目录及同步表单可达性，不运行同步', async ({ page }) => {
  const state = await realDatasetFixture(page)
  await page.goto(`/datasets/${state.dataset_id}/db-catalog`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '数据库目录', exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText('暂无数据库目录', { exact: true })).toBeVisible({ timeout: 60_000 })
  await evidence(page, 'mobile-isolated-db-catalog')
  await page.getByText('表详情', { exact: true }).tap()
  await expect(page.getByText('尚未同步数据库目录', { exact: true })).toBeVisible()
  await evidence(page, 'mobile-isolated-db-detail')
  await page.getByRole('button', { name: '新建同步', exact: true }).first().tap()
  await expect(page.getByRole('dialog', { name: '数据库目录同步' })).toBeVisible()
  await evidence(page, 'mobile-isolated-db-dialog-top')
  await page.getByRole('dialog').getByText('最大表数', { exact: true }).scrollIntoViewIfNeeded()
  await expect(page.getByRole('dialog').getByText('最大表数', { exact: true })).toBeVisible()
  await expect(page.getByRole('dialog').getByText('安全画像', { exact: true })).toBeVisible()
  await evidence(page, 'mobile-isolated-db-dialog-bottom')
  await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).tap()
  await expect(page.getByRole('dialog')).toBeHidden()
})

test('独立 UX：手机检查空图谱的节点搜索，不运行抽取', async ({ page }) => {
  const state = await realDatasetFixture(page)
  await page.goto(`/datasets/${state.dataset_id}/kg`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '数据集图谱', exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText('当前数据集还没有文档', { exact: true })).toBeVisible({ timeout: 60_000 })
  await evidence(page, 'mobile-isolated-kg')
  await page.getByRole('button', { name: '搜索节点', exact: true }).tap()
  await expect(page.getByRole('dialog', { name: '搜索节点' })).toBeVisible()
  await page.getByRole('dialog').getByPlaceholder('搜索实体或事件').fill('资料')
  await evidence(page, 'mobile-isolated-kg-search')
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).tap()
  await expect(page.getByRole('dialog')).toBeHidden()
})
