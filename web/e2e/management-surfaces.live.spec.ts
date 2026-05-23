import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 240_000

function apiBaseUrl(): string {
  return String(
    process.env.PLAYWRIGHT_LIVE_API_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      'http://127.0.0.1:8000'
  ).replace(/\/+$/, '')
}

function liveHeaders(): Record<string, string> {
  return {
    'X-Tenant-ID':
      process.env.PLAYWRIGHT_LIVE_TENANT_ID ||
      process.env.NEXT_PUBLIC_TENANT_ID ||
      DEFAULT_TENANT_ID,
    'X-Account-ID':
      process.env.PLAYWRIGHT_LIVE_USER_ID ||
      process.env.NEXT_PUBLIC_USER_ID ||
      DEFAULT_USER_ID,
    'X-User-ID':
      process.env.PLAYWRIGHT_LIVE_USER_ID ||
      process.env.NEXT_PUBLIC_USER_ID ||
      DEFAULT_USER_ID,
  }
}

async function installLiveAuth(page: Page) {
  const headers = liveHeaders()

  await page.addInitScript(({ tenantId, userId }) => {
    window.localStorage.setItem('mimirq_tenant_id', tenantId)
    window.localStorage.setItem('mimirq_user_id', userId)
  }, {
    tenantId: headers['X-Tenant-ID'],
    userId: headers['X-User-ID'],
  })
}

async function createLiveGroup(
  request: APIRequestContext,
  name: string
): Promise<string> {
  const response = await request.post(`${apiBaseUrl()}/api/v1/groups/`, {
    headers: liveHeaders(),
    data: { name },
  })
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { id?: string }
  expect(String(body.id || '')).toMatch(/\S/)
  return String(body.id)
}

async function deleteLiveGroup(
  request: APIRequestContext,
  groupId: string
): Promise<void> {
  const response = await request.delete(
    `${apiBaseUrl()}/api/v1/groups/${groupId}`,
    { headers: liveHeaders() }
  )
  expect([200, 204]).toContain(response.status())
}

async function patchLiveMemberRole(
  request: APIRequestContext,
  userId: string,
  role: string
): Promise<void> {
  const response = await request.patch(
    `${apiBaseUrl()}/api/v1/rbac/members/${encodeURIComponent(userId)}`,
    {
      headers: liveHeaders(),
      data: { role },
    }
  )
  expect(response.ok()).toBe(true)
}

async function fetchLiveMemberRole(
  request: APIRequestContext,
  userId: string
): Promise<string> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/rbac/members?limit=500`,
    {
      headers: liveHeaders(),
    }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as {
    items?: Array<{ user_id?: string; role?: string }>
  }
  const match = (body.items || []).find(
    (item) => String(item.user_id || '') === userId
  )
  return String(match?.role || '')
}

async function findLiveGroupIdByName(
  request: APIRequestContext,
  groupName: string
): Promise<string> {
  const response = await request.get(`${apiBaseUrl()}/api/v1/groups/?limit=500`, {
    headers: liveHeaders(),
  })
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { items?: Array<{ id?: string; name?: string }> }
  const match = (body.items || []).find((item) => String(item.name || '') === groupName)
  return String(match?.id || '')
}

test.describe('live management surfaces', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('loads management pages that depend on real backend-admin surfaces', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)
    let tempGroupId = ''

    try {
      tempGroupId = await createLiveGroup(
        request,
        `playwright-mgmt-${Date.now()}`
      )

      await page.goto('/prompts', { waitUntil: 'networkidle' })
      await expect(page.getByText('提示词模板')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('模板管理')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.goto('/reports', { waitUntil: 'networkidle' })
      await expect(page.getByText('数据报告与审计概览')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('报告状态')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.goto('/evaluations', { waitUntil: 'networkidle' })
      await expect(page.getByText('评测中心')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(
        page.getByRole('button', { name: '对话评测' })
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(
        page.getByRole('button', { name: 'Golden 评测集' })
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.goto('/usage', { waitUntil: 'networkidle' })
      await expect(
        page.getByRole('heading', { name: '用量/配额' })
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(
        page.getByRole('heading', { name: '租户级配额状态' })
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.goto('/audit', { waitUntil: 'networkidle' })
      await expect(
        page.getByRole('heading', { name: '审计日志' })
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(
        page.getByText(
          '按后端审计日志展示时间、操作者、事件名称、资源/租户与操作明细。'
        )
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.goto('/settings/rbac', { waitUntil: 'networkidle' })
      await expect(
        page.getByRole('heading', { name: '成员权限' })
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(
        page.getByRole('heading', { name: '成员管理' })
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.goto('/settings/groups', { waitUntil: 'networkidle' })
      await expect(
        page.getByRole('heading', { name: '组管理' })
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('新建组')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.goto(`/settings/groups/${encodeURIComponent(tempGroupId)}`, {
        waitUntil: 'networkidle',
      })
      await expect(page.getByRole('heading', { name: '基本信息' })).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByRole('heading', { name: '成员' })).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.goto('/access-review', { waitUntil: 'networkidle' })
      await expect(page).toHaveURL(/\/audit/)
      await expect(
        page.getByRole('heading', { name: '审计日志' })
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      expect(pageErrors).toEqual([])
    } finally {
      if (tempGroupId) {
        await deleteLiveGroup(request, tempGroupId)
      }
    }
  })

  test('creates a real group and adds a member through the management UI', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const groupName = `playwright-ui-group-${Date.now()}`
    let groupId = ''

    try {
      await page.goto('/settings/groups', { waitUntil: 'networkidle' })
      await expect(page.getByRole('heading', { name: '组管理' })).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.getByRole('button', { name: '新建组' }).click()
      await page.getByRole('dialog').waitFor({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await page.locator('#group-name').fill(groupName)
      await page.locator('#group-external-id').fill(`ext-${Date.now()}`)
      await page.getByRole('button', { name: '创建' }).click()

      const groupButton = page.getByRole('button', { name: groupName })
      await expect(groupButton).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await groupButton.click()

      await expect(page.getByText(`组：${groupName}`)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await page.getByRole('button', { name: '添加成员' }).click()
      await page.locator('#group-members').fill('outsider')
      await page.getByRole('button', { name: '添加' }).click()

      await expect(page.getByText('outsider')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      groupId = await findLiveGroupIdByName(request, groupName)
      expect(groupId).toMatch(/\S/)
      expect(pageErrors).toEqual([])
    } finally {
      if (groupId) {
        await deleteLiveGroup(request, groupId)
      }
    }
  })

  test('updates a real tenant member role through the RBAC UI and reverts it', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    try {
      await patchLiveMemberRole(request, 'outsider', 'viewer')

      await page.goto('/settings/rbac', { waitUntil: 'networkidle' })
      await expect(
        page.getByRole('heading', { name: '成员权限' })
      ).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page
        .getByPlaceholder('搜索成员（名称 / 邮箱 / ID）')
        .fill('outsider')

      const row = page.locator('tbody tr').filter({ hasText: 'outsider' }).first()
      await expect(row).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      await row.getByRole('combobox').click()
      await page.getByRole('option', { name: '审计员' }).click()
      await row.getByRole('button', { name: '保存' }).click()

      await expect
        .poll(() => fetchLiveMemberRole(request, 'outsider'), {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBe('auditor')

      await row.getByRole('combobox').click()
      await page.getByRole('option', { name: '查看者' }).click()
      await row.getByRole('button', { name: '保存' }).click()

      await expect
        .poll(() => fetchLiveMemberRole(request, 'outsider'), {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBe('viewer')

      expect(pageErrors).toEqual([])
    } finally {
      await patchLiveMemberRole(request, 'outsider', 'viewer')
    }
  })
})
