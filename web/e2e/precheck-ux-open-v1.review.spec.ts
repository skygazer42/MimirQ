import fs from 'node:fs'
import path from 'node:path'
import { test, expect, type Page } from '@playwright/test'
import { precheckFixture, openPrecheck } from './precheck-workspace.helpers'

const evidence = path.resolve(__dirname, '../../artifacts/rebrand/dataset-precheck-v1/ux-review/open-v1')
fs.mkdirSync(evidence, { recursive: true })

async function capture(page: Page, name: string) {
  await page.screenshot({ path: path.join(evidence, `${name}.png`), fullPage: true, animations: 'disabled' })
  fs.writeFileSync(path.join(evidence, `${name}.txt`), await page.locator('body').innerText())
  const controls = await page.locator('button, input, select, textarea, [role="tab"], a').evaluateAll(elements => elements.map(el => ({
    tag: el.tagName, text: (el.textContent || '').trim(), role: el.getAttribute('role'), label: el.getAttribute('aria-label'),
    placeholder: el.getAttribute('placeholder'), type: el.getAttribute('type'), disabled: (el as HTMLInputElement).disabled,
    checked: (el as HTMLInputElement).checked, value: (el as HTMLInputElement).value, href: el.getAttribute('href'),
  })))
  fs.writeFileSync(path.join(evidence, `${name}-controls.json`), JSON.stringify(controls, null, 2))
  console.log(`EVIDENCE ${name}`)
}

test.setTimeout(120000)

test('open exploration: inspect desktop entrance', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 1000 })
  await precheckFixture(page)
  await openPrecheck(page)
  await expect(page.getByRole('heading', { name: '文档预检', exact: true })).toBeVisible()
  await capture(page, '01-desktop-entrance')
})

test('open exploration: inspect mobile entrance', async ({ page }) => {
  await precheckFixture(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await openPrecheck(page)
  await capture(page, '02-mobile-entrance')
})

test('open exploration: inspect OCR issue and strategy', async ({ page }) => {
  await precheckFixture(page)
  await openPrecheck(page)
  await page.getByRole('button', { name: '查看扫描版 PDF文件', exact: true }).click()
  await expect(page.getByText('product-guide.pdf', { exact: true }).first()).toBeVisible()
  await capture(page, '03-desktop-ocr-files')
  await page.keyboard.press('Escape')
  await capture(page, '04-desktop-back-from-issue')
  await page.getByRole('button', { name: '生成策略', exact: true }).click()
  await capture(page, '05-desktop-strategy-open')
})

for (const viewport of [{ name: 'desktop', width: 1600, height: 1000 }, { name: 'mobile', width: 390, height: 844 }]) {
  test(`open exploration: complete policy task and recover apply failure - ${viewport.name}`, async ({ page }) => {
    const state = await precheckFixture(page)
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await openPrecheck(page)
    await page.getByRole('button', { name: '查看扫描版 PDF文件', exact: true }).click()
    await expect(page.getByText('product-guide.pdf', { exact: true }).first()).toBeVisible()
    await capture(page, `10-${viewport.name}-ocr-files`)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toBeHidden()
    await page.getByRole('button', { name: '生成策略', exact: true }).click()
    await expect(page.getByRole('heading', { name: '生成入库策略', exact: true })).toBeVisible()
    await page.getByText('查看策略 JSON', { exact: true }).click()
    await expect(page.getByText('"pdf-text"', { exact: false }).first()).toBeVisible()
    await capture(page, `11-${viewport.name}-strategy-json`)
    await page.getByText('查看策略 JSON', { exact: true }).click()
    await page.getByRole('button', { name: '应用到数据集', exact: true }).click()
    await expect.poll(() => state.applies.length).toBe(1)
    await expect(page.getByText('已应用入库策略，共 4 条规则', { exact: true }).first()).toBeVisible()
    await capture(page, `12-${viewport.name}-policy-applied`)
    if (await page.getByRole('dialog').isVisible()) await page.getByRole('button', { name: '关闭', exact: true }).click()

    await page.getByRole('button', { name: '生成策略', exact: true }).click()
    await expect(page.getByRole('heading', { name: '生成入库策略', exact: true })).toBeVisible()
    await page.getByText('查看策略 JSON', { exact: true }).click()
    await page.getByRole('checkbox', { name: '覆盖已有入库策略', exact: true }).check()
    state.failApply = '策略应用暂不可用，请稍后重试'
    await page.getByRole('button', { name: '应用到数据集', exact: true }).click()
    await expect(page.getByText(/策略应用暂不可用，请稍后重试/).first()).toBeVisible()
    await expect(page.getByRole('checkbox', { name: '覆盖已有入库策略', exact: true })).toBeChecked()
    await expect(page.getByText('"pdf-text"', { exact: false }).first()).toBeVisible()
    await capture(page, `13-${viewport.name}-apply-failed-context`)
    state.failApply = ''
    await page.getByRole('button', { name: '应用到数据集', exact: true }).click()
    await expect.poll(() => state.applies.length).toBe(3)
    await expect(page.getByText('已应用入库策略，共 4 条规则', { exact: true }).first()).toBeVisible()
    await capture(page, `14-${viewport.name}-apply-retry-result`)
    fs.writeFileSync(path.join(evidence, `15-${viewport.name}-fixture-state.json`), JSON.stringify({
      applies: state.applies, reads: state.reads, starts: state.starts, cancels: state.cancels,
      blocked: state.base.blocked, errors: state.base.errors, url: page.url(), viewport: page.viewportSize(),
    }, null, 2))
  })
}
