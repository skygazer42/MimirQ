import { expect, test } from '@playwright/test'

test.use({ serviceWorkers: 'block' })

test('public readiness and connector refresh errors preserve usable task data', async ({ page }) => {
  let failConnectorRefresh = false
  let administrativeHealthRequests = 0
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace(/\/$/, '')
    const headers = {
      'access-control-allow-origin': '*',
      'access-control-allow-headers': '*',
      'access-control-allow-methods': 'GET, POST, OPTIONS',
    }
    if (request.method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers })
    } else if (path.endsWith('/health/ready')) {
      await route.fulfill({ json: { ok: true, status: 'ready' }, headers })
    } else if (path.endsWith('/meta')) {
      await route.fulfill({
        json: {
          name: 'Ragvia API',
          api_version: 'browser-check',
          build: { sha: 'browser-check' },
          features: { auth_mode: 'header', vector_backend: 'memory', task_queue_enabled: false },
        },
        headers,
      })
    } else if (path.endsWith('/health/details')) {
      administrativeHealthRequests += 1
      await route.fulfill({ status: 403, json: { detail: 'Forbidden' }, headers })
    } else if (path.endsWith('/rbac/me')) {
      await route.fulfill({
        json: {
          account_id: 'viewer',
          tenant_id: '22222222-2222-4222-8222-222222222222',
          role: 'viewer',
          is_active: true,
          permissions: [],
        },
        headers,
      })
    } else if (path.endsWith('/datasets') || path.endsWith('/documents')) {
      await route.fulfill({ json: { total: 0, items: [] }, headers })
    } else if (path.endsWith('/documents/stats')) {
      await route.fulfill({ json: { total: 0, completed: 0, processing: 0, failed: 0, total_size: 0 }, headers })
    } else if (path.endsWith('/connectors/runs')) {
      await route.fulfill(
        failConnectorRefresh
          ? { status: 503, json: { message: '导入任务服务不可用' }, headers }
          : {
              json: {
                total: 1,
                items: [
                  {
                    id: '11111111-1111-4111-8111-111111111111',
                    tenant_id: '22222222-2222-4222-8222-222222222222',
                    connector_id: 'url_batch',
                    status: 'running',
                    created_at: '2026-11-05T00:00:00Z',
                    stats: { total_items: 4, processed_items: 1 },
                  },
                ],
              },
              headers,
            },
      )
    } else {
      await route.fulfill({ status: 503, json: { message: 'Unavailable in isolated browser check' }, headers })
    }
  })

  await page.goto('/zh-CN/knowledge')
  await expect(page.getByRole('heading', { name: '知识库', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '查看后端依赖状态', exact: true })).toContainText('服务已就绪')
  await page.getByRole('button', { name: '任务历史', exact: true }).click()
  await expect(page.getByText('11111111', { exact: false }).first()).toBeVisible()

  failConnectorRefresh = true
  const refreshButton = page.getByRole('button', { name: '刷新', exact: true })
  await refreshButton.focus()
  await page.keyboard.press('Tab')
  await expect(refreshButton).not.toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(refreshButton).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('alert').filter({ hasText: '导入任务服务不可用' })).toBeVisible()
  await expect(page.getByText('11111111', { exact: false }).first()).toBeVisible()
  expect(administrativeHealthRequests).toBe(0)
  expect(pageErrors).toEqual([])
})
