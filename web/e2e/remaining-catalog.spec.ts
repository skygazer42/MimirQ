import { test, expect } from '@playwright/test'
import { datasetRoute, openRemaining, remainingFixture, remainingShot } from './remaining-pages.helpers'

test.use({ timezoneId: 'Asia/Shanghai' })
test('catalog sync failure preserves connection inputs and a reachable footer on phone', async ({ page }) => {
  const state = await remainingFixture(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/api/v1/connectors/runs', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({ status: 503, json: { detail: '同步服务暂不可用' } })
      : route.fallback(),
  )
  await openRemaining(page, datasetRoute('db-catalog'), '数据库目录')
  await page.getByRole('button', { name: '新建同步', exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('textbox', { name: '主机', exact: true }).fill('verification.invalid')
  await dialog.getByRole('textbox', { name: '数据库', exact: true }).fill('verification')
  await dialog.getByRole('textbox', { name: '用户名', exact: true }).fill('ui-verification')
  await dialog.getByLabel('密码', { exact: true }).fill('isolated-fixture-password')
  await dialog.getByRole('button', { name: '开始同步', exact: true }).click()
  await expect(dialog.getByRole('alert').filter({ hasText: '同步服务暂不可用' })).toBeVisible()
  await expect(dialog.getByRole('textbox', { name: '主机', exact: true })).toHaveValue('verification.invalid')
  await expect(dialog.getByLabel('密码', { exact: true })).toHaveValue('isolated-fixture-password')
  await expect(dialog.getByRole('button', { name: '开始同步', exact: true })).toBeVisible()
  await remainingShot(page, 'after-catalog-sync-phone-failure')
  await page.screenshot({ path: test.info().outputPath('catalog-sync-phone-failure.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 620 })
  await expect
    .poll(async () => {
      const bounds = await dialog.getByRole('button', { name: '开始同步', exact: true }).boundingBox()
      return bounds!.y + bounds!.height
    })
    .toBeLessThanOrEqual(620)
  await expect(dialog.getByRole('alert').filter({ hasText: '同步服务暂不可用' })).toBeInViewport({ ratio: 1 })
  await page.screenshot({ path: test.info().outputPath('catalog-sync-short.png'), animations: 'disabled' })
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await expect(page.getByRole('heading', { name: '数据库目录', exact: true })).toBeVisible()
  expect(state.base.blocked).toEqual([])
})

test('catalog keeps schema unknowns and accepted synchronization remains queued', async ({ page }) => {
  const state = await remainingFixture(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  const createdAt = '2026-11-23T14:00:00Z'
  const datasetId = datasetRoute('db-catalog').split('/')[2]
  const table = {
    id: '22222222-2222-4222-8222-222222222222',
    engine: 'sqlserver',
    db_name: 'warehouse',
    schema_name: 'dbo',
    table_name: 'orders',
    table_type: 'BASE TABLE',
    comment: '订单结构',
    fingerprint: 'fixture-schema',
    created_at: createdAt,
    columns: [
      {
        id: 'column-id',
        table_id: '22222222-2222-4222-8222-222222222222',
        ordinal: 1,
        name: 'order_id',
        data_type: 'bigint',
        nullable: false,
        created_at: createdAt,
      },
      {
        id: 'column-unknown',
        table_id: '22222222-2222-4222-8222-222222222222',
        ordinal: 2,
        name: 'contact',
        data_type: null,
        nullable: null,
        created_at: createdAt,
      },
    ],
  }
  let run: Record<string, unknown> | null = null
  let submitted: Record<string, unknown> | null = null
  const reads: string[] = []
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname
    if (pathname === `/api/v1/datasets/${datasetId}/db-catalog/tables`) {
      reads.push(url.search)
      const query = url.searchParams.get('q') || ''
      const engine = url.searchParams.get('engine')
      const items = 'warehouse.dbo.orders'.includes(query) && (!engine || engine === table.engine) ? [table] : []
      return route.fulfill({ json: { total: items.length, items } })
    }
    if (pathname === `/api/v1/datasets/${datasetId}/db-catalog/tables/${table.id}`)
      return route.fulfill({ json: table })
    if (pathname === `/api/v1/datasets/${datasetId}/db-catalog/profiles`)
      return route.fulfill({
        json: {
          total: 1,
          items: [
            {
              id: 'profile-fixture',
              table_id: table.id,
              entitlement_hash: 'fixture',
              profile: { row_count_estimate: 120 },
              sample_meta: {},
              created_at: createdAt,
            },
          ],
        },
      })
    if (pathname === '/api/v1/connectors/runs' && request.method() === 'POST') {
      submitted = request.postDataJSON() as Record<string, unknown>
      run = {
        id: '77777777-7777-4777-8777-777777777777',
        tenant_id: 'tenant-fixture',
        dataset_id: datasetId,
        connector_id: 'mysql_catalog',
        status: 'pending',
        stats: {},
        created_at: createdAt,
      }
      return route.fulfill({ status: 202, json: run })
    }
    if (pathname === '/api/v1/connectors/runs' && request.method() === 'GET')
      return route.fulfill({ json: { total: run === null ? 0 : 1, items: run === null ? [] : [run] } })
    return route.fallback()
  })
  await openRemaining(page, datasetRoute('db-catalog'), '数据库目录')
  await expect(page.getByText('order_id', { exact: true })).toBeVisible()
  await expect(page.getByText('—', { exact: true })).toHaveCount(2)
  await page.screenshot({ path: test.info().outputPath('catalog-structure.png'), animations: 'disabled' })
  const search = page.getByRole('searchbox', { name: '搜索数据库表', exact: true })
  await search.fill('not-found')
  await expect(page.getByText('没有匹配的表', { exact: true }).first()).toBeVisible()
  await search.fill('')
  await expect.poll(() => reads.some((query) => new URLSearchParams(query).get('q') === 'not-found')).toBe(true)
  await page.getByRole('button', { name: '新建同步', exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'mysql', exact: true }).click()
  await dialog.getByLabel('主机', { exact: true }).fill('catalog.invalid')
  await dialog.getByLabel('数据库', { exact: true }).fill('warehouse')
  await dialog.getByLabel('用户名', { exact: true }).fill('catalog-reader')
  await dialog.getByLabel('密码', { exact: true }).fill('isolated-fixture-password')
  await dialog.getByRole('button', { name: '开始同步', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByText('数据集最近一次目录同步 · 排队中', { exact: true })).toBeVisible({ timeout: 20000 })
  await expect(page.getByText('连接器 mysql_catalog', { exact: true })).toBeVisible()
  expect(submitted).toMatchObject({ connector_id: 'mysql_catalog', dataset_id: datasetId, config: { port: 3306 } })
  await page.getByRole('tab', { name: '同步记录', exact: true }).click()
  await expect(
    page.getByRole('table', { name: '数据库目录同步记录' }).getByRole('cell', { name: '排队中', exact: true }),
  ).toBeVisible()
  await expect(page.getByText(/同步完成|已完成同步/)).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath('catalog-queued.png'), animations: 'disabled' })
  const runTime = page.getByRole('table', { name: '数据库目录同步记录' }).locator('time')
  await expect(runTime).toHaveAttribute('datetime', createdAt)
  await expect(runTime).toContainText('22:00:00')
  await expect(runTime).toContainText('GMT+8')
  await page.setViewportSize({ width: 390, height: 620 })
  await page.getByRole('button', { name: '表详情', exact: true }).click()
  await expect(page.getByRole('heading', { name: '数据集同步记录', exact: true })).toBeInViewport({ ratio: 1 })
  await expect(runTime).toBeInViewport({ ratio: 1 })
  expect(state.base.blocked).toEqual([])
})
