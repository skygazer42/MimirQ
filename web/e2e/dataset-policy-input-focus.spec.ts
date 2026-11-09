import fs from 'node:fs'
import path from 'node:path'
import { test, expect } from '@playwright/test'
import { datasetPolicyFixture, openPolicy, policyEvidence, policyShot } from './dataset-policy.helpers'

for (const theme of ['light', 'dark'] as const) test(`${theme} focused empty rule input remains distinguishable`, async ({ page }) => {
  await datasetPolicyFixture(page, theme); await page.setViewportSize({ width: 320, height: 740 }); await openPolicy(page)
  await page.getByRole('button', { name: '新增规则', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '新增规则', exact: true }), input = dialog.getByLabel('规则名称', { exact: true })
  await input.focus()
  const colors = await input.evaluate(element => {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1
    const context = canvas.getContext('2d')!
    const rgba = (color: string) => { context.clearRect(0, 0, 1, 1); context.fillStyle = color; context.fillRect(0, 0, 1, 1); return [...context.getImageData(0, 0, 1, 1).data] }
    const style = getComputedStyle(element), background = rgba(style.backgroundColor)
    const composite = (color: string) => { const values = rgba(color), alpha = values[3] / 255; return values.slice(0, 3).map((value, i) => value * alpha + background[i] * (1 - alpha)) }
    const luminance = (values: number[]) => { const rgb = values.slice(0, 3).map(value => value / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4); return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2] }
    const contrast = (color: string) => { const a = luminance(composite(color)), b = luminance(background); return (Math.max(a, b) + .05) / (Math.min(a, b) + .05) }
    const placeholder = getComputedStyle(element, '::placeholder').color
    return { background: style.backgroundColor, border: style.borderTopColor, placeholder, focusVisible: element.matches(':focus-visible'), borderContrast: contrast(style.borderTopColor), placeholderContrast: contrast(placeholder) }
  })
  fs.mkdirSync(policyEvidence, { recursive: true }); fs.writeFileSync(path.join(policyEvidence, `focused-input-${theme}.json`), JSON.stringify(colors, null, 2))
  await policyShot(page, `focused-input-${theme}`)
  expect(colors.focusVisible).toBe(true); expect(colors.borderContrast).toBeGreaterThanOrEqual(3); expect(colors.placeholderContrast).toBeGreaterThanOrEqual(4.5)
  await input.fill('产品资料规则'); await expect(input).toHaveValue('产品资料规则')
})
