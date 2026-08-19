import { expect, test } from '@playwright/test'

test('clears login errors and keeps first-time setup reachable at low viewport heights', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 640 })
  await page.route('**/api/v1/meta', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ features: { auth_mode: 'jwt' } }),
    })
  })
  await page.route('**/api/v1/auth/login', async (route) => {
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Invalid credentials' }),
    })
  })

  await page.goto('/auth')
  await page.getByLabel('账号').fill('unknown-user')
  await page.getByLabel('密码').fill('wrong-password')
  await page.locator('form').getByRole('button', { name: '登 录', exact: true }).click()
  const formAlert = page.locator('form [role="alert"]')
  await expect(formAlert).toContainText('Invalid credentials')

  await page.getByRole('button', { name: '首次设置', exact: true }).click()
  await expect(formAlert).toHaveCount(0)

  const frame = page.locator('#main-content').locator('..')
  const scrollState = await frame.evaluate((element) => ({
    clientHeight: element.clientHeight,
    overflowY: getComputedStyle(element).overflowY,
    scrollHeight: element.scrollHeight,
  }))

  expect(scrollState.overflowY).toBe('auto')
  expect(scrollState.scrollHeight).toBeGreaterThan(scrollState.clientHeight)

  const submitButton = page.getByRole('button', { name: '创建初始管理员', exact: true })
  await submitButton.scrollIntoViewIfNeeded()
  await expect(submitButton).toBeInViewport()
})
