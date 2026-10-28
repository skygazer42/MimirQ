import fs from 'node:fs'
import path from 'node:path'
import { test, expect } from '@playwright/test'
import { realDatasetFixture, openRemaining, remainingEvidence, remainingShot } from './remaining-pages.helpers'

test('a script draft is persisted only to the dedicated real governance profile', async ({ page, request }) => {
  const state = await realDatasetFixture(page)
  await page.setViewportSize({ width: 1600, height: 1000 })
  await openRemaining(page, '/data-governance/common-lines', '重复内容规则')
  await page.getByRole('button', { name: new RegExp(state.governance_profile_key) }).click()
  const api = `http://127.0.0.1:8000/api/v1/pipeline/governance-profiles/${state.governance_profile_ref}`
  const saved = page.waitForResponse(response => new URL(response.url()).pathname.endsWith(`/governance-profiles/${state.governance_profile_ref}`) && response.request().method() === 'PATCH')
  await page.locator('input[type=file]').first().setInputFiles({ name: 'ui-verification-draft.py', mimeType: 'text/x-python', buffer: Buffer.from('# UI verification draft; never executed.\ndef transform(text):\n    return text\n') })
  const response = await saved
  expect(response.ok(), await response.text()).toBeTruthy()
  await expect(page.getByText('已导入 1 个处理脚本草案', { exact: true })).toBeVisible()
  const headers = { 'X-User-ID': state.user_id, 'X-Tenant-ID': state.tenant_id }
  const actual = await (await request.get(api, { headers })).json()
  const draft = actual.payload.processing_scripts.find((item: { name: string }) => item.name === 'ui-verification-draft.py')
  expect(draft.enabled).toBe(false)
  expect(draft.content).toContain('def transform(text)')
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: new RegExp(state.governance_profile_key) }).click()
  const refreshed = await (await request.get(api, { headers })).json()
  expect(refreshed.payload.processing_scripts.find((item: { name: string }) => item.name === draft.name)).toEqual(draft)
  await remainingShot(page, 'after-common-lines-real')
  fs.writeFileSync(path.join(remainingEvidence, 'common-lines-real-save.json'), JSON.stringify({ profile_id: actual.id, script: draft.name, disabled: true, persisted: true }, null, 2))
})

test('monitor and industry rules can read real APIs without external models', async ({ page }) => {
  const state = await realDatasetFixture(page)
  await page.setViewportSize({ width: 1600, height: 1000 })
  const documents = page.waitForResponse(response => new URL(response.url()).pathname.replace(/\/$/, '') === '/api/v1/documents' && response.ok())
  await openRemaining(page, `/knowledge/ingestion?mode=execution-monitor&datasetId=${state.dataset_id}`, '入库执行监控')
  await documents
  await expect(page.getByRole('heading', { name: '当前范围暂无执行任务', exact: true })).toBeVisible()
  await remainingShot(page, 'after-execution-monitor-real')
  const detail = page.waitForResponse(response => /\/industry-rules\/rulesets\/[^/]+$/.test(new URL(response.url()).pathname) && response.ok())
  await openRemaining(page, '/governance/industry-rules', '行业规则')
  await detail
  await expect(page.getByText('正在读取规则…', { exact: true })).toHaveCount(0)
  await remainingShot(page, 'after-industry-rules-real')
})
