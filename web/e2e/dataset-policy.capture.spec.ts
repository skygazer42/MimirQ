// Artifact capture only. Functional assertions live in dataset-policy.spec.ts.
import fs from 'node:fs'
import path from 'node:path'
import { test, expect } from '@playwright/test'
import { datasetPolicyFixture, openPolicy, policyEvidence, policyShot } from './dataset-policy.helpers'

for (const theme of ['light', 'dark'] as const) test(`capture final ${theme} dataset policy surfaces`, async ({ page }) => {
  await datasetPolicyFixture(page, theme)
  for (const view of [{ name: 'desktop', width: 1600, height: 1000 }, { name: 'phone', width: 390, height: 844 }]) {
    await page.setViewportSize({ width: view.width, height: view.height }); await openPolicy(page)
    await expect(page.getByRole('table', { name: '入库规则', exact: true })).toBeVisible()
    await policyShot(page, `final-${theme}-${view.name}`)
    const html = (await page.content()).replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '').replace(/\b(href|src)="\/(?!\/)/g, '$1="http://127.0.0.1:3000/')
    fs.mkdirSync(policyEvidence, { recursive: true }); fs.writeFileSync(path.join(policyEvidence, `final-${theme}-${view.name}.html`), html)
  }
  await page.setViewportSize({ width: 320, height: 740 }); await openPolicy(page); await policyShot(page, `final-${theme}-320`)
  await page.getByRole('button', { name: '新增规则', exact: true }).click(); await policyShot(page, `final-${theme}-phone-editor`)
})
