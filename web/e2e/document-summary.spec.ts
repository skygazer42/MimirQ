import { expect, test } from '@playwright/test'

import type { Document } from '../types'
import processingFixtures from '@/components/document-detail-dialog/document-processing.fixture.json'
import { policyDatasetId } from './dataset-policy.helpers'
import { installCommonApiMocks, UPLOADED_DOCUMENT_ID } from './enterprise-quality-telemetry.helpers'
import { profileSummary } from './remaining-pages.helpers'

test.use({ serviceWorkers: 'block' })

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`reads processing facts and copies the actual active version at width ${viewport.width}`, async ({
    page,
    context,
  }) => {
    await page.setViewportSize(viewport)
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    let activeVersion: string | null = null
    let firstDetailRead = true
    let releaseInitialRead!: () => void
    const initialRead = new Promise<void>((resolve) => {
      releaseInitialRead = resolve
    })
    let stored: Document = {
      id: UPLOADED_DOCUMENT_ID,
      filename: 'processing-facts.md',
      file_type: 'md',
      file_size: 100,
      total_characters: 100,
      chunk_count: 0,
      status: 'completed',
      processing_progress: 100,
      processing_attempts: 0,
      publication_status: 'draft',
      created_at: '2026-11-16T00:00:00Z',
      updated_at: '2026-11-16T00:00:00Z',
      ...processingFixtures.empty,
    }
    await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
    await page.route(
      (url) => url.pathname.startsWith(`/api/v1/datasets/${policyDatasetId}`),
      async (route) => {
        const path = new URL(route.request().url()).pathname
        const datasetPath = `/api/v1/datasets/${policyDatasetId}`
        if (path === datasetPath)
          await route.fulfill({ json: { id: policyDatasetId, name: 'Processing facts', document_count: 1 } })
        else if (path === `${datasetPath}/profile/summary`) await route.fulfill({ json: profileSummary() })
        else if (path === `${datasetPath}/profile/scan-runs`) await route.fulfill({ json: { total: 0, items: [] } })
        else if (path.startsWith(`${datasetPath}/profile/findings/`))
          await route.fulfill({ json: { total: 1, items: [stored] } })
        else await route.fallback()
      },
    )
    await page.route(
      (url) => url.pathname.startsWith(`/api/v1/documents/${UPLOADED_DOCUMENT_ID}`),
      async (route) => {
        const path = new URL(route.request().url()).pathname
        const documentPath = `/api/v1/documents/${UPLOADED_DOCUMENT_ID}`
        if (path === documentPath) {
          if (firstDetailRead) {
            firstDetailRead = false
            await initialRead
          }
          await route.fulfill({ json: stored })
        } else if (path === `${documentPath}/versions`)
          await route.fulfill({ json: { document_id: stored.id, active_pipeline_hash: activeVersion, items: [] } })
        else if (path === `${documentPath}/chunks`) await route.fulfill({ json: { total: 0, items: [] } })
        else if (path === `${documentPath}/access`)
          await route.fulfill({
            json: { mode: 'inherit', owner_id: null, partial_member_list: [], partial_group_list: [] },
          })
        else if (path === `${documentPath}/lifecycle`) await route.fulfill({ json: { publication_status: 'draft' } })
        else await route.fallback()
      },
    )
    const dialog = page.getByRole('dialog', { name: stored.filename, exact: true })
    async function openDetail() {
      await page.goto(`/datasets/${policyDatasetId}/profile`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('button', { name: '查看正文过短文件', exact: true }).click()
      await page.getByRole('button', { name: stored.filename, exact: true }).click()
      await expect(dialog).toBeVisible()
    }
    function fieldValue(label: string) {
      return dialog
        .locator('dt')
        .filter({ hasText: new RegExp(`^${label}$`) })
        .locator('..')
        .locator('dd')
    }
    await openDetail()
    await expect(fieldValue('向量索引')).toHaveText('未提供')
    await expect(fieldValue('BM25 索引')).toHaveText('未提供')
    await expect(fieldValue('激活版本')).toHaveText('未提供')
    await expect(dialog.getByRole('button', { name: '复制版本标识', exact: true })).toHaveCount(0)
    releaseInitialRead()
    await expect(fieldValue('向量索引')).toHaveText('未启用')
    await expect(fieldValue('BM25 索引')).toHaveText('未启用')
    await expect(fieldValue('正文字符数')).toHaveText('0')

    const rulePacks = processingFixtures.processed.pipeline.governance_rule_packs
    stored = { ...stored, ...processingFixtures.processed }
    activeVersion = 'active-from-version-response'
    await openDetail()
    await expect(fieldValue('实际解析器')).toHaveText('text')
    await expect(fieldValue('请求解析器')).toHaveText('无')
    await expect(fieldValue('正文字符数')).toHaveText('0')
    await expect(fieldValue('目标长度')).toHaveText('0')
    await expect(fieldValue('重叠长度')).toHaveText('0')
    await expect(fieldValue('向量索引')).toHaveText('未启用')
    await expect(fieldValue('BM25 索引')).toHaveText('已启用')
    await expect(fieldValue('激活版本')).toHaveText(activeVersion)
    await expect(fieldValue('最近版本')).toHaveText('last-canonical-version')
    await expect(fieldValue('规则包')).toHaveAttribute('title', rulePacks.join(', '))
    await expect(dialog.getByText('custom-legal-sections', { exact: true })).toBeVisible()
    await expect(dialog).not.toContainText('old-active-snapshot')
    await fieldValue('BM25 索引').scrollIntoViewIfNeeded()
    await page.screenshot({
      path: `../.frontend-structure/20261112-full-frontend-guidelines/document-summary/summary-${viewport.width}.png`,
    })
    await dialog.getByRole('button', { name: '复制版本标识', exact: true }).click()
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(activeVersion)
    expect(
      await dialog
        .locator('dl')
        .evaluateAll((lists) => lists.every((element) => element.scrollWidth <= element.clientWidth)),
    ).toBe(true)

    activeVersion = null
    await openDetail()
    await expect(fieldValue('激活版本')).toHaveText('未提供')
    await expect(fieldValue('查看版本')).toHaveText('未提供')
    await expect(dialog.getByRole('button', { name: '复制版本标识', exact: true })).toHaveCount(0)
    await expect(fieldValue('最近版本')).toHaveText('last-canonical-version')
    expect(pageErrors).toEqual([])
  })
}
