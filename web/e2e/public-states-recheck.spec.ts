import { test, expect } from '@playwright/test'
import { openPublicState, publicStateFixture } from './public-states.helpers'

test('unchanged access produces transient completion feedback and the next grant clears it', async ({ page }) => {
  const state = await publicStateFixture(page)
  await openPublicState(page, '/settings/rbac', '无权限访问')
  await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await expect(page.getByText('校验完成，当前账号仍无法访问此页面。', { exact: true })).toBeVisible()
  state.settingsRead = true
  await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await expect(page.getByRole('heading', { name: '成员权限', exact: true })).toBeVisible({ timeout: 30000 })
  await expect(page.getByText('校验完成，当前账号仍无法访问此页面。', { exact: true })).toHaveCount(0)
  state.settingsRead = false
  await openPublicState(page, '/prompts', '入口未开放')
  await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await expect(page.getByText('校验完成，此入口仍未向当前账号开放。', { exact: true })).toBeVisible()
  state.promptsOpen = true
  await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await expect(page.getByRole('heading', { name: '提示词', exact: true })).toBeVisible({ timeout: 30000 })
  await expect(page.getByText('校验完成，此入口仍未向当前账号开放。', { exact: true })).toHaveCount(0)
  expect(state.policyState.blocked).toEqual([])
})
