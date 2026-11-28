import { expect, test } from '@playwright/test'
import { auditDocumentId, lastBatchFixture } from './remaining-last-batch.helpers'

test('nebula distinguishes unavailable counts from confirmed empty chunks and retains the last read', async ({
  page,
}) => {
  const state = await lastBatchFixture(page)
  state.failChunks = true
  await page.goto('/knowledge/nebula', { waitUntil: 'domcontentloaded' })
  const heading = page.getByRole('heading', { name: '语义星云', exact: true })
  await expect(heading).toBeVisible({ timeout: 60000 })
  const workspace = page.locator('[data-operational-workspace="语义星云"]')
  await expect(page.getByRole('alert').filter({ hasText: '切片读取暂不可用' })).toBeVisible({ timeout: 30000 })
  await expect(workspace.getByText('0 文档 · 0 切片', { exact: true })).toHaveCount(0)
  await expect(workspace.getByText('未取得切片', { exact: true })).toBeVisible()

  state.failChunks = false
  await page
    .getByRole('alert')
    .filter({ hasText: '切片读取暂不可用' })
    .getByRole('button', { name: '重新读取', exact: true })
    .click()
  await expect(workspace.getByText('1 文档 · 4 切片', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '图例与定位', exact: true }).click()
  await page.getByRole('combobox', { name: '定位切片', exact: true }).selectOption(`${auditDocumentId}:chunk-1`)
  await expect(page.getByRole('dialog', { name: '切片详情', exact: true })).toContainText('设备维护第 2 节')
  await page.keyboard.press('Escape')

  state.emptyChunks = true
  await workspace.getByRole('button', { name: '重新读取', exact: true }).click()
  await expect(workspace.getByText('1 文档 · 0 切片', { exact: true })).toBeVisible()
  state.failChunks = true
  await workspace.getByRole('button', { name: '重新读取', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '切片读取暂不可用' })).toBeVisible({ timeout: 30000 })
  await expect(workspace.getByText('1 文档 · 0 切片', { exact: true })).toBeVisible()
})
