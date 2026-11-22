import { test, expect } from '@playwright/test'
import { lastBatchFixture, auditDocumentId } from './remaining-last-batch.helpers'
import { remainingShot } from './remaining-pages.helpers'

test('capture the current final-batch route entry points', async ({ page }) => {
  test.setTimeout(600000)
  await lastBatchFixture(page)
  for (const [name, route, title] of [
    ['document-health', `/knowledge/${auditDocumentId}/health`, '文档健康审计'],
    ['observability', '/observability', '可观测性'],
    ['evidence-debugger', '/knowledge/evidence', '证据调试'],
    ['semantic-nebula', '/knowledge/nebula', '语义星云'],
    ['oidc-callback', '/auth/oidc/callback', '单点登录未完成'],
    ['saml-callback', '/auth/saml/callback?error=saml_session_missing', '单点登录未完成'],
  ]) {
    await page.goto(route, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible({ timeout: 60000 })
    if (name === 'semantic-nebula') await expect(page.locator('canvas')).toBeVisible({ timeout: 60000 })
    await remainingShot(page, `current-entry-${name}`)
  }
})
