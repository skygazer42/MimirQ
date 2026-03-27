import { expect, test } from '@playwright/test'

import {
  type EnterpriseTelemetryMockState,
  UPLOADED_DOCUMENT_FILENAME,
  UPLOADED_DOCUMENT_ID,
  installCommonApiMocks,
} from './enterprise-quality-telemetry.helpers'

test('command menu natural-language handoff routes into chat autorun', async ({ page }) => {
  const state: EnterpriseTelemetryMockState = { uploaded: true, parsingDocuments: [] }
  const prompt = '请帮我总结当前页面有哪些可继续操作的重点。'

  await installCommonApiMocks(page, state)
  await page.goto('/')

  await expect(page.getByPlaceholder('问点什么... (Shift + Enter 换行)')).toBeVisible({ timeout: 60_000 })

  await page.getByRole('button', { name: '打开命令搜索' }).click()

  const commandDialog = page.getByRole('dialog')
  await expect(commandDialog).toBeVisible()

  const commandInput = commandDialog.getByRole('combobox')
  await expect(commandInput).toBeVisible()
  await commandInput.fill(prompt)
  await expect(page.getByRole('option', { name: /执行自然语言指令/ })).toBeVisible()

  await commandInput.press('Enter')

  await expect.poll(() => state.chatRequests?.at(-1)?.message || '').toBe(prompt)
  await expect.poll(() => new URL(page.url()).searchParams.get('conversation')).toBe('conv-e2e-1')
  await expect(page.getByText('已完成智能对话验证。')).toBeVisible({ timeout: 60_000 })
})

test('document viewer restores expanded layout and active tab after reload', async ({ page }) => {
  const state: EnterpriseTelemetryMockState = { uploaded: true, parsingDocuments: [] }

  await installCommonApiMocks(page, state)
  await page.goto(`/?doc=${encodeURIComponent(UPLOADED_DOCUMENT_ID)}`)

  await expect(page.getByRole('heading', { name: UPLOADED_DOCUMENT_FILENAME })).toBeVisible({ timeout: 60_000 })

  await page.getByRole('button', { name: '展开' }).click()

  const chunksTab = page.getByRole('tab', { name: '智能切片' })
  await chunksTab.click()
  await expect(chunksTab).toHaveAttribute('data-state', 'active')
  await expect(page.getByRole('button', { name: '收起', exact: true })).toBeVisible()

  await page.reload()

  await expect(page.getByRole('heading', { name: UPLOADED_DOCUMENT_FILENAME })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('tab', { name: '智能切片' })).toHaveAttribute('data-state', 'active')
  await expect(page.getByRole('button', { name: '收起', exact: true })).toBeVisible()
})
