import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 300_000

type GovernanceProfileSummary = {
  id?: string
  key?: string
  name?: string
  is_system?: boolean
}

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
  await page.addInitScript(
    ({ tenantId, userId }) => {
      window.localStorage.setItem('mimirq_tenant_id', tenantId)
      window.localStorage.setItem('mimirq_user_id', userId)
    },
    {
      tenantId: headers['X-Tenant-ID'],
      userId: headers['X-User-ID'],
    }
  )
}

async function listProfilesByQuery(
  request: APIRequestContext,
  query: string
): Promise<GovernanceProfileSummary[]> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/pipeline/governance-profiles?q=${encodeURIComponent(query)}&include_builtin=true&limit=200`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { items?: GovernanceProfileSummary[] }
  return Array.isArray(body.items) ? body.items : []
}

async function deleteProfileByRef(
  request: APIRequestContext,
  profileRef: string
): Promise<void> {
  const response = await request.delete(
    `${apiBaseUrl()}/api/v1/pipeline/governance-profiles/${encodeURIComponent(profileRef)}`,
    { headers: liveHeaders() }
  )
  expect([200, 204]).toContain(response.status())
}

test.describe('live governance profiles page', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('creates and deletes a real custom governance profile on the deployed page host', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const uniqueSuffix = `${Date.now()}`
    const profileName = `Playwright Governance ${uniqueSuffix}`
    const profileKey = `playwright-governance-${uniqueSuffix}`
    const profileDescription =
      'Disposable governance profile created by the live Playwright proof.'

    let createdProfileRef = ''

    try {
      await page.goto('/data-governance/profiles', { waitUntil: 'networkidle' })
      await expect(
        page.getByRole('heading', { name: '治理配置' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      await page.getByRole('button', { name: '新建' }).click()

      const dialog = page.getByRole('dialog')
      await expect(
        dialog.getByRole('heading', { name: '新建治理模板' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      await dialog.locator('#gp-name').fill(profileName)
      await dialog.locator('#gp-key').fill(profileKey)
      await dialog.locator('#gp-desc').fill(profileDescription)

      await dialog.getByRole('button', { name: '保存' }).click()
      await expect(dialog).toHaveCount(0, { timeout: LIVE_EXPECT_TIMEOUT_MS })

      await expect
        .poll(async () => {
          const items = await listProfilesByQuery(request, profileKey)
          return items.find((item) => String(item.key || '').trim() === profileKey)
            ? 1
            : 0
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBe(1)

      const createdProfiles = await listProfilesByQuery(request, profileKey)
      const createdProfile = createdProfiles.find(
        (item) => String(item.key || '').trim() === profileKey
      )
      expect(createdProfile).toBeTruthy()
      expect(createdProfile?.is_system).toBe(false)
      createdProfileRef =
        String(createdProfile?.id || '').trim() ||
        String(createdProfile?.key || '').trim()

      const searchInput = page.getByPlaceholder('搜索名称、说明或 key')
      await searchInput.fill(profileKey)

      const card = page
        .locator('div')
        .filter({ hasText: profileName })
        .filter({ hasText: profileKey })
        .first()
      await expect(card).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      await card.getByRole('button', { name: '更多操作' }).click()
      await page.getByRole('menuitem', { name: '删除' }).click()

      const deleteDialog = page.getByRole('alertdialog')
      await expect(
        deleteDialog.getByRole('heading', { name: '删除该治理配置？' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await expect(deleteDialog.getByText(profileName)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await deleteDialog.getByRole('button', { name: '删除' }).click()

      await expect
        .poll(async () => {
          const items = await listProfilesByQuery(request, profileKey)
          return items.some(
            (item) => String(item.key || '').trim() === profileKey
          )
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBe(false)

      createdProfileRef = ''
      await expect(card).toHaveCount(0)
      expect(pageErrors).toEqual([])
    } finally {
      if (createdProfileRef) {
        await deleteProfileByRef(request, createdProfileRef)
      }
    }
  })
})
