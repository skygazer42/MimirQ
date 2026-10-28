import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/auth/policy', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        initialized: true, registration_enabled: true, bootstrap_enabled: false,
        bootstrap_token_required: false, password_min_length: 8,
      }),
    })
  })
})

test('keeps authentication readable when reduced motion is enabled', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/auth')
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()

  await expect.poll(async () => page.locator('#main-content').evaluate((element) => {
    const blurredAncestors: string[] = []
    for (let current: Element | null = element; current; current = current.parentElement) {
      const filter = getComputedStyle(current).filter
      if (filter !== 'none' && filter !== 'blur(0px)') blurredAncestors.push(filter)
    }
    return blurredAncestors
  })).toEqual([])
})

test('clears login errors and keeps registration reachable at low viewport heights', async ({ page }) => {
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
  await page.getByLabel('密码', { exact: true }).fill('wrong-password')
  await page.locator('form').getByRole('button', { name: '登录', exact: true }).click()
  const formAlert = page.locator('form [role="alert"]')
  await expect(formAlert).toContainText('账号或密码不正确，请重试。')

  await page.getByRole('button', { name: '注册', exact: true }).click()
  await expect(formAlert).toHaveCount(0)

  const frame = page.locator('#main-content').locator('..')
  const scrollState = await frame.evaluate((element) => ({
    clientHeight: element.clientHeight,
    overflowY: getComputedStyle(element).overflowY,
    scrollHeight: element.scrollHeight,
  }))

  expect(scrollState.overflowY).toBe('auto')
  expect(scrollState.scrollHeight).toBeGreaterThan(scrollState.clientHeight)

  const submitButton = page.locator('form').getByRole('button', { name: '注册', exact: true })
  await submitButton.scrollIntoViewIfNeeded()
  await expect(submitButton).toBeInViewport()
})
