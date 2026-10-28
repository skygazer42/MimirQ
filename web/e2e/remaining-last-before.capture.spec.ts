import { test, expect } from '@playwright/test'
import { lastBatchFixture, auditDocumentId } from './remaining-last-batch.helpers'
import { remainingShot } from './remaining-pages.helpers'

test('retain original final-batch screens before replacement', async ({ page }) => {
  test.setTimeout(600000)
  await lastBatchFixture(page)
  for (const [name, route, title] of [
    ['document-health', `/knowledge/${auditDocumentId}/health`, '文档健康审计'],
    ['observability', '/observability', '监控面板'],
    ['evidence-debugger', '/knowledge/evidence', 'Evidence Workbench'],
    ['semantic-nebula', '/knowledge/nebula', '语义星云'],
    ['oidc-callback', '/auth/oidc/callback', 'SSO sign-in failed'],
    ['saml-callback', '/auth/saml/callback', 'SAML sign-in failed'],
  ]) {
    await page.goto(route, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText(title, { exact: true }).first()).toBeVisible({ timeout: 60000 })
    if (name === 'semantic-nebula') await expect(page.locator('canvas')).toBeVisible({ timeout: 60000 })
    await remainingShot(page, `before-${name}`)
  }
})
