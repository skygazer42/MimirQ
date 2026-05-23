import fs from 'node:fs/promises'

import { expect, test, type APIRequestContext, type Download, type Page } from '@playwright/test'

const LIVE_BACKEND_ENABLED = process.env.PLAYWRIGHT_LIVE_BACKEND === '1'
const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000000'
const DEFAULT_USER_ID = 'demo'
const LIVE_EXPECT_TIMEOUT_MS = 60_000
const LIVE_TEST_TIMEOUT_MS = 300_000
const RULESET_NAME = 'industrial_control'
const REWRITE_QUERY = 'RS-485 授权报错怎么办'
type IndustryRulesetSummary = {
  name?: string
  glossary_count?: number
  pattern_count?: number
  intent_count?: number
}

type IndustryRulesRewritePreviewResponse = {
  expanded_query?: string
  changed?: boolean
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

async function fetchIndustryRulesets(
  request: APIRequestContext
): Promise<IndustryRulesetSummary[]> {
  const response = await request.get(
    `${apiBaseUrl()}/api/v1/industry-rules/rulesets`,
    { headers: liveHeaders() }
  )
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { rulesets?: IndustryRulesetSummary[] }
  return Array.isArray(body.rulesets) ? body.rulesets : []
}

async function previewRewrite(
  request: APIRequestContext,
  query: string
): Promise<IndustryRulesRewritePreviewResponse> {
  const response = await request.post(
    `${apiBaseUrl()}/api/v1/industry-rules/preview-rewrite`,
    {
      headers: liveHeaders(),
      data: {
        ruleset: RULESET_NAME,
        query,
      },
    }
  )
  expect(response.ok()).toBe(true)
  return (await response.json()) as IndustryRulesRewritePreviewResponse
}

async function readDownloadJson(download: Download): Promise<Record<string, unknown>> {
  const path = await download.path()
  expect(path).toBeTruthy()
  const content = await fs.readFile(String(path), 'utf8')
  return JSON.parse(content) as Record<string, unknown>
}

test.describe('live industry rules workbench', () => {
  test.skip(
    !LIVE_BACKEND_ENABLED,
    'Requires PLAYWRIGHT_LIVE_BACKEND=1 and a running backend'
  )

  test('loads a real ruleset, proves rewrite preview, and exports the current ruleset on the deployed page host', async ({
    page,
    request,
  }) => {
    test.setTimeout(LIVE_TEST_TIMEOUT_MS)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installLiveAuth(page)

    try {
      const rulesets = await fetchIndustryRulesets(request)
      expect(
        rulesets.some((item) => String(item.name || '').trim() === RULESET_NAME)
      ).toBe(true)

      const rewrite = await previewRewrite(request, REWRITE_QUERY)
      expect(rewrite.changed).toBe(true)
      expect(String(rewrite.expanded_query || '')).toContain('RS-485 通讯线')

      await page.goto('/governance/industry-rules', { waitUntil: 'networkidle' })
      await expect(page.getByText('行业规则库')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      await page.locator('#industry-rules-ruleset').click()
      await page.getByRole('option', { name: RULESET_NAME }).click()

      await page.locator('#industry-rules-preview-query').fill(REWRITE_QUERY)
      await expect(page.getByText('已命中规则并改写')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })
      await expect(page.getByText('RS-485 通讯线')).toBeVisible({
        timeout: LIVE_EXPECT_TIMEOUT_MS,
      })

      const downloadPromise = page.waitForEvent('download')
      await page.getByRole('button', { name: '导出当前规则集' }).click()
      const download = await downloadPromise
      expect(download.suggestedFilename()).toBe(`${RULESET_NAME}.json`)
      const exported = await readDownloadJson(download)
      expect(String(exported.ruleset || '')).toBe(RULESET_NAME)
      expect(exported.glossary).toBeTruthy()

      expect(pageErrors).toEqual([])
    } finally {
      // No remote mutations in this proof path.
    }
  })
})
