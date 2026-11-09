import fs from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'
import { datasetPolicyFixture, openPolicy, policyEvidence, policyShot } from './dataset-policy.helpers'

async function switchContrast(control: ReturnType<import('@playwright/test').Page['getByRole']>) {
  return control.evaluate(element => {
    const luminance = (color: string) => {
      const rgb = color.match(/[\d.]+/g)!.slice(0, 3).map(Number).map(value => { const part = value / 255; return part <= .04045 ? part / 12.92 : ((part + .055) / 1.055) ** 2.4 })
      return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2]
    }
    const track = getComputedStyle(element).backgroundColor, thumb = getComputedStyle(element.querySelector('span')!).backgroundColor
    const a = luminance(track), b = luminance(thumb)
    return { track, thumb, ratio: (Math.max(a, b) + .05) / (Math.min(a, b) + .05) }
  })
}

for (const theme of ['light', 'dark'] as const) test(`${theme} switches retain visible contrast in table and rule editor`, async ({ page }) => {
  await datasetPolicyFixture(page, theme); await openPolicy(page)
  const checks: Record<string, unknown> = {}
  for (const name of ['PDF 文本文档', 'Markdown 与纯文本']) {
    const result = await switchContrast(page.getByRole('switch', { name: `启用规则 ${name}`, exact: true }))
    checks[name] = result; expect(result.ratio).toBeGreaterThanOrEqual(3)
  }
  await policyShot(page, `theme-${theme}-table`)
  await page.getByRole('button', { name: '编辑规则 PDF 文本文档', exact: true }).click()
  const editor = page.getByRole('dialog', { name: '编辑规则', exact: true })
  const result = await switchContrast(editor.getByRole('switch', { name: '启用此规则', exact: true }))
  checks.editor = result; expect(result.ratio).toBeGreaterThanOrEqual(3)
  await policyShot(page, `theme-${theme}-editor`)
  fs.mkdirSync(policyEvidence, { recursive: true }); fs.writeFileSync(path.join(policyEvidence, `switch-${theme}.json`), JSON.stringify(checks, null, 2))
})
