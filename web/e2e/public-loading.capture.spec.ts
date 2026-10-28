// Artifact capture of the real loading components; no production debug route is added.
import fs from 'node:fs'
import path from 'node:path'
import { test, expect } from '@playwright/test'
import { openPublicState, publicStateEvidence, publicStateFixture, publicStateShot } from './public-states.helpers'

test('capture actual loading component outputs in desktop and phone layouts', async ({ page }) => {
  const stage = process.env.BOUNDARY_CAPTURE_STAGE ?? 'after'
  await publicStateFixture(page)
  await openPublicState(page, '/settings/rbac', '无权限访问')
  const css = await page.locator('link[rel="stylesheet"]').evaluateAll(links => links.map(link => (link as HTMLLinkElement).href))
  const inline = await page.locator('html').getAttribute('style')
  for (const size of [{ width: 1600, height: 1000, name: 'desktop' }, { width: 390, height: 844, name: 'phone' }]) {
    await page.setViewportSize(size)
    for (const name of ['root', 'dataset', 'knowledge', 'evaluation', 'graph', 'settings']) {
      const body = fs.readFileSync(path.resolve(publicStateEvidence, `../rendered/${stage}/${name}.html`), 'utf8')
      const html = `<!doctype html><html lang="zh-CN" data-surface-theme="ocean" style="${inline ?? ''}"><head><meta charset="utf-8">${css.map(href => `<link rel="stylesheet" href="${href}">`).join('')}</head><body class="font-sans">${body}</body></html>`
      await page.route(`**/__boundary-evidence__/loading-${name}.html`, route => route.fulfill({ status: 200, contentType: 'text/html', body: html }))
      await page.goto(`/__boundary-evidence__/loading-${name}.html`, { waitUntil: 'load' })
      await expect(page.getByRole('status')).toHaveCount(1)
      await publicStateShot(page, `${stage}-loading-${name}-${size.name}`)
      fs.mkdirSync(publicStateEvidence, { recursive: true }); fs.writeFileSync(path.join(publicStateEvidence, `${stage}-loading-${name}-${size.name}.html`), html)
    }
  }
})
