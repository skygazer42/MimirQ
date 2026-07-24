import { expect, test } from '@playwright/test'

test('browser reaches the live backend and shows the login form', async ({ page }) => {
  await page.goto('/auth')
  await expect(page.getByRole('button', { name: '登录' })).toBeVisible()
  await expect(page.getByLabel('账号')).toBeVisible()
  await expect(page.getByLabel('密码')).toBeVisible()

  const probes = await page.evaluate(async () => {
    const paths = ['/api/v1/health', '/api/v1/health/ready', '/api/v1/meta']
    return Promise.all(
      paths.map(async (path) => {
        const response = await fetch(path, { headers: { Accept: 'application/json' } })
        return {
          path,
          status: response.status,
          contentType: response.headers.get('content-type') || '',
        }
      })
    )
  })

  expect(probes).toEqual([
    expect.objectContaining({ path: '/api/v1/health', status: 200, contentType: expect.stringContaining('json') }),
    expect.objectContaining({ path: '/api/v1/health/ready', status: 200, contentType: expect.stringContaining('json') }),
    expect.objectContaining({ path: '/api/v1/meta', status: 200, contentType: expect.stringContaining('json') }),
  ])
})
