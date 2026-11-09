import { test, expect } from '@playwright/test'
import { openInjectedRouteError, openPublicState, publicStateFixture, publicStateShot } from './public-states.helpers'
import { policyRoute } from './dataset-policy.helpers'

test('permission denial preserves its boundary and rechecks access without exposing the page', async ({ page }) => {
  const state = await publicStateFixture(page)
  await openPublicState(page, '/settings/rbac', '无权限访问')
  await expect(page.locator('[data-page-status]')).toBeVisible()
  await expect(page.getByRole('table', { name: '成员权限', exact: true })).toHaveCount(0)
  await page.getByText('权限信息', { exact: true }).click(); await expect(page.locator('[data-page-status]')).toContainText('settings.read')
  await publicStateShot(page, 'denied-desktop')
  const reads = state.accessReads; state.settingsRead = true
  await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await expect(page.getByRole('heading', { name: '成员权限', exact: true })).toBeVisible({ timeout: 30000 })
  await expect(page.getByRole('heading', { name: '还没有成员', exact: true })).toBeVisible()
  expect(state.accessReads).toBeGreaterThan(reads); expect(state.policyState.blocked).toEqual([])
})

test('unavailable permission metadata stays distinct from denied access and can recover', async ({ page }) => {
  const state = await publicStateFixture(page, 'dark'); state.failAccess = true
  await openPublicState(page, '/settings/rbac', '无法确认权限')
  await expect(page.getByRole('heading', { name: '无权限访问', exact: true })).toHaveCount(0)
  await publicStateShot(page, 'access-unavailable-dark')
  state.failAccess = false; state.settingsRead = true
  await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await expect(page.getByRole('heading', { name: '成员权限', exact: true })).toBeVisible({ timeout: 30000 })
  expect(state.policyState.blocked).toEqual([])
})

test('closed navigation entry rechecks its actual visibility setting on phones', async ({ page }) => {
  const state = await publicStateFixture(page); await page.setViewportSize({ width: 390, height: 844 })
  await openPublicState(page, '/prompts', '入口未开放')
  await expect(page.locator('[data-page-status]')).toContainText('提示词')
  await expect(page.getByRole('button', { name: '新建模板', exact: true })).toHaveCount(0)
  await publicStateShot(page, 'entry-closed-phone')
  state.promptsOpen = true; await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await expect(page.getByRole('heading', { name: '提示词', exact: true })).toBeVisible({ timeout: 30000 })
  expect(state.policyState.blocked).toEqual([])
})

test('404 has working return navigation and no horizontal overflow on phones', async ({ page }) => {
  const state = await publicStateFixture(page, 'dark'); await page.setViewportSize({ width: 320, height: 740 })
  await openPublicState(page, '/__missing-boundary-fixture__', '页面不存在')
  await publicStateShot(page, 'not-found-dark-phone')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('link', { name: '前往知识库', exact: true }).click()
  await expect(page).toHaveURL(/\/knowledge(?:\?|$)/, { timeout: 60000 })
  await expect(page.getByRole('heading', { name: '知识库', exact: true })).toBeVisible({ timeout: 60000 })
  expect(state.policyState.blocked).toEqual([])
})

test('the shared error boundary retries the real route after a captured render failure', async ({ page }) => {
  const state = await publicStateFixture(page)
  await openInjectedRouteError(page, state)
  await expect(page.locator('[data-page-status]')).toBeVisible()
  await publicStateShot(page, 'route-error-desktop')
  state.policyState.policy.rules![0].name = 'PDF 文本文档'
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(policyRoute))
  await expect(page.getByRole('heading', { name: '入库策略', exact: true })).toBeVisible({ timeout: 60000 })
  await expect(page.getByRole('table', { name: '入库规则', exact: true })).toBeVisible()
  expect(state.policyState.blocked).toEqual([])
})

test('the existing local development access mode still enters the page', async ({ page }) => {
  const state = await publicStateFixture(page, 'light', false)
  await openPublicState(page, '/settings/rbac', '成员权限')
  await expect(page.getByRole('heading', { name: '无权限访问', exact: true })).toHaveCount(0)
  expect(state.policyState.blocked).toEqual([])
})
