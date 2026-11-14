import { expect, test } from '@playwright/test'

import type { DatasetListResponse } from '../types/datasets'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

const datasetResponse: DatasetListResponse = {
  items: [{ id: 'dataset-style-pilot', tenant_id: 'tenant-pilot', name: '运维手册', permission: 'all_team_members' }],
  total: 1,
  facets: { scope_total: 1, filtered_total: 1, status_counts: { active: 1 } },
}
const emptyResponse: DatasetListResponse = {
  items: [],
  total: 0,
  facets: { scope_total: 0, filtered_total: 0, status_counts: {} },
}
const datasetListUrl = (url: URL) => ['/api/v1/datasets', '/api/v1/datasets/'].includes(url.pathname)

test.use({ colorScheme: 'light' })

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.route('**/api/v1/**', (route) => route.fulfill({ json: { items: [], total: 0 } }))
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
})

test('数据集成功返回后展示实际列表', async ({ page }, testInfo) => {
  await page.route(datasetListUrl, (route) => route.fulfill({ json: datasetResponse }))
  await page.goto('/datasets')
  const catalog = page.locator('[data-dataset-catalog-scroll]')
  await expect(catalog.getByText('运维手册', { exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('heading', { name: '暂无数据集' })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('datasets-success.png'), animations: 'disabled' })
})

test('成功返回空列表才展示空数据状态', async ({ page }, testInfo) => {
  await page.route(datasetListUrl, (route) => route.fulfill({ json: emptyResponse }))
  await page.goto('/datasets')
  await expect(page.getByRole('heading', { name: '暂无数据集' })).toBeVisible({ timeout: 60_000 })
  await page.screenshot({ path: testInfo.outputPath('datasets-empty.png'), animations: 'disabled' })
})

test('请求进行中明确展示加载状态', async ({ page }, testInfo) => {
  let releaseRequest!: () => void
  const requestGate = new Promise<void>((resolve) => {
    releaseRequest = resolve
  })
  await page.route(datasetListUrl, async (route) => {
    await requestGate
    await route.fulfill({ json: datasetResponse })
  })
  try {
    await page.goto('/datasets')
    await expect(page.getByRole('heading', { name: '数据集', exact: true })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('status').filter({ hasText: '正在加载数据集' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '暂无数据集' })).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('datasets-loading.png'), animations: 'disabled' })
    releaseRequest()
    await expect(page.locator('[data-dataset-catalog-scroll]').getByText('运维手册', { exact: true })).toBeVisible()
  } finally {
    releaseRequest()
  }
})

test('请求失败不显示空数据且允许重试恢复', async ({ page }, testInfo) => {
  let failRequest = true
  await page.route(datasetListUrl, (route) =>
    failRequest
      ? route.fulfill({ status: 503, json: { error: 'SERVICE_UNAVAILABLE', message: '数据集服务暂时不可用' } })
      : route.fulfill({ json: datasetResponse }),
  )
  await page.goto('/datasets')
  const error = page.getByRole('alert').filter({ hasText: '加载数据集失败' })
  await expect(error).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('heading', { name: '暂无数据集' })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('datasets-error.png'), animations: 'disabled' })
  failRequest = false
  await error.getByRole('button', { name: '重试', exact: true }).click()
  await expect(page.locator('[data-dataset-catalog-scroll]').getByText('运维手册', { exact: true })).toBeVisible()
  await expect(error).toHaveCount(0)
})

test('后台刷新失败保留已有列表并允许重试', async ({ page }, testInfo) => {
  let failRequest = false
  await page.route(datasetListUrl, (route) =>
    failRequest
      ? route.fulfill({ status: 503, json: { message: '数据集服务暂时不可用' } })
      : route.fulfill({ json: datasetResponse }),
  )
  await page.goto('/datasets')
  const item = page.locator('[data-dataset-catalog-scroll]').getByText('运维手册', { exact: true })
  await expect(item).toBeVisible({ timeout: 60_000 })
  failRequest = true
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  const error = page.getByRole('alert').filter({ hasText: '加载数据集失败' })
  await expect(error).toBeVisible({ timeout: 60_000 })
  await expect(item).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('datasets-cached-error.png'), animations: 'disabled' })
  failRequest = false
  await error.getByRole('button', { name: '重试', exact: true }).click()
  await expect(error).toHaveCount(0)
  await expect(item).toBeVisible()
})

test('搜索排序刷新仍使用服务端参数且创建入口可用', async ({ page }) => {
  await page.route(datasetListUrl, (route) => route.fulfill({ json: datasetResponse }))
  await page.goto('/datasets')
  await expect(page.getByRole('heading', { name: '数据集', exact: true })).toBeVisible({ timeout: 60_000 })
  const searchRequest = page.waitForRequest((request) => {
    const url = new URL(request.url())
    return datasetListUrl(url) && url.searchParams.get('q') === '手册'
  })
  await page.getByRole('textbox', { name: '搜索数据集' }).fill('手册')
  await searchRequest
  const sortRequest = page.waitForRequest((request) => {
    const url = new URL(request.url())
    return (
      datasetListUrl(url) &&
      url.searchParams.get('q') === '手册' &&
      url.searchParams.get('order_by') === 'name' &&
      url.searchParams.get('order_dir') === 'asc'
    )
  })
  await page.getByText('默认排序', { exact: true }).click()
  await page.getByRole('option', { name: '按名称', exact: true }).click()
  await sortRequest
  const refreshRequest = page.waitForRequest((request) => {
    const url = new URL(request.url())
    return datasetListUrl(url) && url.searchParams.get('q') === '手册' && url.searchParams.get('order_by') === 'name'
  })
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await refreshRequest
  await page.getByRole('button', { name: '新建数据集', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('heading', { name: '新建数据集', exact: true })).toBeVisible()
})
