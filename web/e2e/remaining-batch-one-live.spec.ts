import fs from 'node:fs'
import path from 'node:path'
import { test, expect } from '@playwright/test'
import { openRemaining, realDatasetFixture, remainingEvidence, remainingShot } from './remaining-pages.helpers'

test('migrated dataset routes read the dedicated data through the real API', async ({ page }) => {
  test.setTimeout(300000)
  const state = await realDatasetFixture(page)
  await page.setViewportSize({ width: 1600, height: 1000 })
  const reads: Array<{ url: string; status: number }> = []
  page.on('response', (response) => {
    if (response.url().includes('/api/v1/') && !response.url().includes('/observability/frontend'))
      reads.push({ url: new URL(response.url()).pathname, status: response.status() })
  })
  for (const [route, title] of [
    ['profile', '数据画像'],
    ['health', '健康概览'],
    ['tables', '表格资产'],
    ['db-catalog', '数据库目录'],
    ['evidence', '证据库'],
    ['kg', '数据集图谱'],
  ]) {
    const suffix = (
      {
        profile: '/profile/summary',
        health: '/health',
        tables: '/tables',
        'db-catalog': '/db-catalog/tables',
        evidence: '/evidence/suites',
        kg: '/documents',
      } as Record<string, string>
    )[route]
    const complete = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname.replace(/\/$/, '').endsWith(suffix) && response.request().method() === 'GET',
    )
    await openRemaining(page, `/datasets/${state.dataset_id}/${route}`, title)
    expect((await complete).ok()).toBeTruthy()
    await expect(page.getByText(state.name, { exact: true }).first()).toBeVisible({ timeout: 60000 })
    if (route === 'profile') await expect(page.getByText('正在读取数据画像…', { exact: true })).toHaveCount(0)
    if (route === 'health') await expect(page.locator('[data-health-document-count]')).toHaveText('0')
    if (route === 'tables')
      await expect(page.getByRole('heading', { name: '当前数据集尚无结构化表格资产', exact: true })).toBeVisible()
    if (route === 'db-catalog')
      await expect(page.getByRole('heading', { name: '尚未同步数据库目录', exact: true })).toBeVisible()
    if (route === 'evidence') await expect(page.getByText('正在读取证据条目…', { exact: true })).toHaveCount(0)
    if (route === 'kg') await expect(page.getByText('当前数据集还没有文档', { exact: true })).toBeVisible()
    await remainingShot(page, `after-${route}-real`)
  }
  fs.writeFileSync(path.join(remainingEvidence, 'batch-one-real-reads.json'), JSON.stringify(reads, null, 2))
  expect(reads.filter((read) => read.url.includes(state.dataset_id) && read.status >= 400)).toEqual([])
})

test('a new evidence suite is saved by the real API and readable after reload', async ({ page, request }) => {
  const state = await realDatasetFixture(page)
  await openRemaining(page, `/datasets/${state.dataset_id}/evidence`, '证据库')
  await page.getByRole('button', { name: '新建', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: '新建证据集', exact: true })).toBeVisible()
  const name = `ui-verification-evidence-${Date.now()}`
  await dialog.getByLabel('名称', { exact: true }).fill(name)
  const creation = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/v1/evidence/suites',
  )
  await dialog.getByRole('button', { name: '创建', exact: true }).click()
  const response = await creation
  expect(response.ok()).toBeTruthy()
  const suite = await response.json()
  expect(suite.dataset_id).toBe(state.dataset_id)
  await expect(dialog).toHaveCount(0)
  const readback = await request.get(`/api/v1/evidence/suites/${suite.id}`, {
    headers: { 'X-User-ID': state.user_id, 'X-Tenant-ID': state.tenant_id },
  })
  expect((await readback.json()).name).toBe(name)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByText(name, { exact: true }).first()).toBeVisible({ timeout: 60000 })
  fs.writeFileSync(
    path.join(remainingEvidence, 'evidence-real-save.json'),
    JSON.stringify({ suite_id: suite.id, dataset_id: state.dataset_id, persisted: true }, null, 2),
  )
})
