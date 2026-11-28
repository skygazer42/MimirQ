import { expect, test, type Page } from '@playwright/test'

import { makeProfileScan, makeProfileSummary } from '../test/dataset-profile-fixtures'
import { datasetRoute, remainingFixture } from './remaining-pages.helpers'
import { policyDatasetId } from './dataset-policy.helpers'

async function emptyProfile(page: Page) {
  const state = await remainingFixture(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  state.profile = makeProfileSummary({ dataset_id: policyDatasetId })
  state.scanRuns = []
  return state
}

async function openProfile(page: Page) {
  await page.goto(datasetRoute('profile'), { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('tablist', { name: '数据画像视图', exact: true })).toBeVisible({ timeout: 30_000 })
}

test('空库只显示入库引导，没有伪健康、更新时间和空图表', async ({ page }, testInfo) => {
  await emptyProfile(page)
  await openProfile(page)
  await expect(page.getByRole('heading', { name: '先上传入库文档', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '深度扫描', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '导出画像', exact: true })).toBeDisabled()
  await expect(page.getByText('0 类问题', { exact: true })).toHaveCount(0)
  await expect(page.getByText(/画像更新于|统计更新于/)).toHaveCount(0)
  await expect(page.locator('.recharts-wrapper')).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('empty-overview.png'), animations: 'disabled' })
  await page.getByRole('tab', { name: '分布分析', exact: true }).click()
  await expect(page.getByRole('heading', { name: '先上传入库文档', exact: true })).toBeVisible()
  await expect(page.getByRole('tablist', { name: '分布分析分类' })).toHaveCount(0)
  await page.getByRole('tab', { name: '扫描历史', exact: true }).click()
  await expect(page.getByRole('heading', { name: '尚无扫描记录', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '扫描历史', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '导出 HTML', exact: true })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('empty-history.png'), animations: 'disabled' })
})

test('有文档无扫描显示首次扫描入口，不提前展示质检结论', async ({ page }) => {
  const state = await emptyProfile(page)
  state.profile.total_documents = 1
  await openProfile(page)
  await expect(page.getByRole('heading', { name: '启动首次深度扫描', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '导出画像', exact: true })).toBeDisabled()
  await expect(page.getByRole('table', { name: '画像问题清单' })).toHaveCount(0)
  await page.getByRole('button', { name: '配置深度扫描', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('heading', { name: '深度扫描', exact: true })).toBeVisible()
})

test('重新进入时从历史恢复运行中扫描，不被摘要缓存误导', async ({ page }) => {
  const state = await emptyProfile(page)
  state.profile.total_documents = 1
  const running = makeProfileScan(state.profile, { status: 'running', progress: 40, finished_at: null, summary: {} })
  state.scanRuns = [running]
  let polls = 0
  await page.route('**/api/v1/datasets/*/profile/scan-runs/' + running.id, async (route) => {
    polls += 1
    await route.fulfill({ json: { ...running, progress: 60 } })
  })
  await openProfile(page)
  await expect(page.getByRole('heading', { name: '扫描进行中', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '正在扫描（60%）', exact: true })).toBeDisabled()
  expect(polls).toBeGreaterThan(0)
  await expect(page.getByRole('button', { name: '导出画像', exact: true })).toBeDisabled()
})

test('首次扫描失败在引导区保留真实原因，不伪装成尚未就绪', async ({ page }) => {
  const state = await emptyProfile(page)
  state.profile.total_documents = 1
  state.scanRuns = [
    makeProfileScan(state.profile, { status: 'failed', summary: {}, error_message: '文档读取失败，请检查来源文件' }),
  ]
  await openProfile(page)
  await expect(page.getByRole('heading', { name: '扫描失败', exact: true })).toBeVisible()
  await expect(page.getByText('文档读取失败，请检查来源文件', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '导出画像', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '配置深度扫描', exact: true })).toBeEnabled()
})

test('已完成但尚未保存有效结果时仍禁止导出，刷新后可进入画像', async ({ page }) => {
  const state = await emptyProfile(page)
  state.profile.total_documents = 1
  state.scanRuns = [makeProfileScan(state.profile, { summary: {} })]
  await openProfile(page)
  await expect(page.getByRole('heading', { name: '尚无可用扫描结果', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '导出画像', exact: true })).toBeDisabled()
  state.scanRuns = [makeProfileScan(state.profile)]
  await page.getByRole('button', { name: '重新读取结果', exact: true }).click()
  await expect(page.getByRole('button', { name: '导出画像', exact: true })).toBeEnabled()
  await expect(page.getByRole('heading', { name: '最近有效扫描', exact: true })).toBeVisible()
})

test('保留更早有效扫描，零命中不等于全部通过，分布空态集中说明', async ({ page }, testInfo) => {
  const state = await emptyProfile(page)
  state.profile.total_documents = 1
  state.profile.findings = Array.from({ length: 14 }, (_, index) => ({
    key: 'finding-' + index,
    label: '检测维度 ' + (index + 1),
    severity: 'info' as const,
    count: 0,
    description: null,
  }))
  const snapshot = {
    ...state.profile,
    latest_scan_run: {
      id: 'cached-running',
      kind: 'profile',
      status: 'running',
      progress: 50,
      requested_by: null,
      created_at: null,
      started_at: null,
      finished_at: null,
      error_message: null,
    },
  }
  const completed = makeProfileScan(snapshot)
  state.scanRuns = [
    makeProfileScan(state.profile, { id: 'new-failed', status: 'failed', summary: {}, error_message: '扫描未完成' }),
    completed,
  ]
  await openProfile(page)
  await expect(page.getByRole('button', { name: '导出画像', exact: true })).toBeEnabled()
  await expect(page.locator('[data-page-title-icon="dataset-profile"]')).toBeVisible()
  await expect(page.getByText('当前画像没有问题命中记录。', { exact: true })).toBeVisible()
  await expect(page.getByText('最近一次扫描尝试失败：', { exact: true })).toBeVisible()
  await expect(page.getByText(/全部通过/)).toHaveCount(0)
  await expect(page.locator('time[datetime="' + completed.finished_at + '"]')).toBeVisible()
  await expect(page.getByText(/统计更新于/)).toBeVisible()
  const unit = page.getByText('正文长度 P90', { exact: true }).locator('..').locator('dd small')
  await expect(unit).toHaveText('字符')
  await page.screenshot({ path: testInfo.outputPath('ready-overview.png'), animations: 'disabled' })
  await page.getByRole('tab', { name: '分布分析', exact: true }).click()
  await expect(page.getByRole('tablist', { name: '分布分析分类' })).toBeVisible()
  for (const [category, count] of [
    ['文档分布', 8],
    ['切片质量', 4],
    ['解析与风险', 5],
  ] as const) {
    await page.getByRole('tab', { name: category, exact: true }).click()
    await expect(page.getByRole('heading', { name: '当前分类暂无分布统计', exact: true })).toHaveCount(1)
    await expect(page.getByText('当前画像记录 1 篇文档，本分类的分布计数均为空或 0。', { exact: true })).toBeVisible()
    await expect(page.getByText('最近扫描：失败', { exact: true })).toBeVisible()
    await expect(page.getByRole('list', { name: '分布项目', exact: true }).getByRole('listitem')).toHaveCount(count)
    await expect(page.getByText('暂无可展示的分布数据', { exact: true })).toHaveCount(0)
  }
  await page.getByRole('tab', { name: '文档分布', exact: true }).click()
  await expect(page.locator('.recharts-cartesian-axis')).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('ready-distribution.png'), animations: 'disabled' })
})

test('部分分布已有计数时保留真实图表和其他分类', async ({ page }, testInfo) => {
  const state = await emptyProfile(page)
  state.profile.total_documents = 1
  state.profile.by_status = { completed: 1 }
  state.scanRuns = [makeProfileScan(state.profile)]
  await openProfile(page)
  await page.getByRole('tab', { name: '分布分析', exact: true }).click()
  await expect(page.getByRole('heading', { name: '当前分类暂无分布统计', exact: true })).toHaveCount(0)
  await expect(page.getByText('状态分布', { exact: true })).toBeVisible()
  await expect(page.getByText('格式分布', { exact: true })).toBeVisible()
  await expect(page.locator('.recharts-wrapper')).toHaveCount(1)
  await page.screenshot({ path: testInfo.outputPath('partial-distribution.png'), animations: 'disabled' })
})

test('导出入口统一，HTML 保持脱敏且不冒充固定历史快照', async ({ page }) => {
  const state = await emptyProfile(page)
  state.profile.total_documents = 1
  state.scanRuns = [makeProfileScan(state.profile)]
  await page.route('**/api/v1/datasets/*/profile/export-html*', async (route) => {
    expect(new URL(route.request().url()).searchParams.get('redact')).toBe('true')
    await route.fulfill({ contentType: 'text/html', body: '<html><body>当前画像</body></html>' })
  })
  await openProfile(page)
  await expect(page.getByRole('button', { name: '导出画像', exact: true })).toBeEnabled()
  await page.getByRole('tab', { name: '扫描历史', exact: true }).click()
  await expect(page.getByRole('table', { name: '数据集画像扫描运行记录' })).toContainText('已完成')
  await expect(page.getByText('离线报告', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '导出 HTML', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '导出画像', exact: true }).click()
  const download = page.waitForEvent('download')
  await page.getByRole('menuitem', { name: '脱敏 HTML 报告', exact: true }).click()
  const report = await download
  expect(report.suggestedFilename()).toMatch(/\.profile\.html$/)
  expect(await report.failure()).toBeNull()
})

test('扫描记录读取失败不当作未扫描，手机空态可操作且无横向溢出', async ({ page }, testInfo) => {
  const state = await emptyProfile(page)
  state.profile.total_documents = 1
  state.failHistory = true
  await page.setViewportSize({ width: 390, height: 844 })
  const failedRead = page.waitForResponse(
    (response) => new URL(response.url()).pathname.endsWith('/profile/scan-runs') && response.status() === 503,
  )
  await openProfile(page)
  await failedRead
  await expect(page.getByRole('alert').filter({ hasText: '扫描历史读取暂不可用' })).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('heading', { name: '启动首次深度扫描', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '导出画像', exact: true })).toBeDisabled()
  state.failHistory = false
  await page.getByRole('button', { name: '重新读取扫描历史', exact: true }).click()
  await expect(page.getByRole('heading', { name: '启动首次深度扫描', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.screenshot({ path: testInfo.outputPath('mobile-first-scan.png'), animations: 'disabled' })
})
