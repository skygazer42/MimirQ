import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 300_000

type LiveDataset = {
  id?: string
  name?: string
  description?: string | null
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

async function listDatasets(request: APIRequestContext): Promise<LiveDataset[]> {
  const response = await request.get(`${apiBaseUrl()}/api/v1/datasets/?skip=0&limit=200`, {
    headers: liveHeaders(),
  })
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { items?: LiveDataset[] }
  return Array.isArray(body.items) ? body.items : []
}

async function getDataset(
  request: APIRequestContext,
  datasetId: string
): Promise<LiveDataset> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/datasets/${encodeURIComponent(datasetId)}`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as LiveDataset
}

async function deleteDatasetById(
  request: APIRequestContext,
  datasetId: string
): Promise<void> {
  const response = await request.delete(
    `${apiBaseUrl()}/api/v1/datasets/${encodeURIComponent(datasetId)}`,
    { headers: liveHeaders() }
  )
  expect([200, 204]).toContain(response.status())
}

test.describe('live datasets workbench', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('creates, edits, and deletes a real dataset on the deployed page host', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    const uniqueSuffix = `${Date.now()}`
    const datasetName = `Playwright Dataset ${uniqueSuffix}`
    const updatedDescription = `Updated by deployed datasets live proof ${uniqueSuffix}.`

    let datasetId = ''

    try {
      await page.goto('/datasets', { waitUntil: 'networkidle' })
      await expect(
        page.getByRole('heading', { name: '数据集' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      await page.getByRole('button', { name: '新建数据集' }).click()

      const createDialog = page.getByRole('dialog')
      await expect(
        createDialog.getByRole('heading', { name: '新建数据集' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })

      await createDialog.locator('#ds-name').fill(datasetName)
      await createDialog.locator('#ds-desc').fill(
        'Created by the deployed datasets live proof.'
      )
      await createDialog.getByRole('button', { name: '确认创建' }).click()
      await expect(createDialog).toHaveCount(0, { timeout: LIVE_EXPECT_TIMEOUT_MS })

      await expect
        .poll(async () => {
          const datasets = await listDatasets(request)
          const created = datasets.find(
            (item) => String(item.name || '').trim() === datasetName
          )
          datasetId = String(created?.id || '').trim()
          return datasetId
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toMatch(/\S/)

      await page.getByPlaceholder('搜索数据集、描述或 ID...').fill(datasetName)

      const datasetCard = page
        .getByRole('button')
        .filter({ hasText: datasetName })
        .first()
      await expect(datasetCard).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await datasetCard.click()

      await expect(page.getByText('当前选中数据集')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText(datasetName, { exact: true }).first()).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.getByRole('button', { name: '编辑数据集' }).last().click()

      const editDialog = page.getByRole('dialog')
      await expect(
        editDialog.getByRole('heading', { name: '编辑数据集' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await editDialog.locator('#ds-desc').fill(updatedDescription)
      await editDialog.getByRole('button', { name: '保存变更' }).click()
      await expect(editDialog).toHaveCount(0, { timeout: LIVE_EXPECT_TIMEOUT_MS })

      await expect
        .poll(async () => {
          const current = await getDataset(request, datasetId)
          return String(current.description || '').trim()
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBe(updatedDescription)

      await expect(page.getByText(updatedDescription)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.getByRole('button', { name: '删除数据集' }).last().click()

      const deleteDialog = page.getByRole('alertdialog')
      await expect(
        deleteDialog.getByRole('heading', { name: '删除数据集？' })
      ).toBeVisible({ timeout: LIVE_EXPECT_TIMEOUT_MS })
      await expect(deleteDialog.getByText(datasetName)).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await deleteDialog.getByRole('button', { name: '删除' }).click()

      await expect
        .poll(async () => {
          const datasets = await listDatasets(request)
          return datasets.some((item) => String(item.id || '') === datasetId)
        }, {
          timeout: LIVE_EXPECT_TIMEOUT_MS,
        })
        .toBe(false)

      datasetId = ''
      expect(pageErrors).toEqual([])
    } finally {
      if (datasetId) {
        await deleteDatasetById(request, datasetId)
      }
    }
  })
})
