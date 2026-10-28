import fs from 'node:fs'
import path from 'node:path'
import { test, expect, type Page } from '@playwright/test'
import { precheckFixture, openPrecheck } from './precheck-workspace.helpers'

const evidence = path.resolve(__dirname, '../../artifacts/rebrand/dataset-precheck-v1/ux-recheck/recheck-v1')
fs.mkdirSync(evidence, { recursive: true })
const successText = '已应用入库策略，共 4 条规则'

async function capture(page: Page, name: string) {
  await page.screenshot({ path: path.join(evidence, `${name}.png`), fullPage: true, animations: 'disabled' })
  fs.writeFileSync(path.join(evidence, `${name}.txt`), await page.locator('body').innerText())
  const geometry = await page.locator('[role="dialog"], [role="dialog"] h2, [role="dialog"] button, [data-sonner-toast]').evaluateAll(elements => elements.map(el => {
    const bounds = el.getBoundingClientRect()
    const style = getComputedStyle(el)
    return {
      tag: el.tagName, text: (el.textContent || '').trim(), role: el.getAttribute('role'), label: el.getAttribute('aria-label'),
      bounds: { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height },
      display: style.display, visibility: style.visibility, opacity: style.opacity,
      state: el.getAttribute('data-state'), removed: el.getAttribute('data-removed'),
    }
  }))
  fs.writeFileSync(path.join(evidence, `${name}-geometry.json`), JSON.stringify(geometry, null, 2))
  console.log(`EVIDENCE ${name}`)
}

test.setTimeout(120000)

for (const viewport of [{ name: 'desktop', width: 1600, height: 1000 }, { name: 'mobile', width: 390, height: 844 }]) {
  test(`UX recheck: original policy task and apply recovery - ${viewport.name}`, async ({ page }) => {
    const state = await precheckFixture(page)
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    const observations: Record<string, unknown> = {}
    try {
      await openPrecheck(page)
      await capture(page, `01-${viewport.name}-entrance`)
      await page.getByRole('button', { name: '查看扫描版 PDF文件', exact: true }).click()
      await expect(page.getByText('product-guide.pdf', { exact: true }).first()).toBeVisible()
      await capture(page, `02-${viewport.name}-ocr-files`)
      await page.keyboard.press('Escape')
      await expect(page.getByRole('dialog')).toBeHidden()
      await page.getByRole('button', { name: '生成策略', exact: true }).click()
      await expect(page.getByRole('heading', { name: '生成入库策略', exact: true })).toBeVisible()
      await capture(page, `03-${viewport.name}-strategy-default`)
      observations.defaultDialog = await page.getByRole('dialog').innerText()
      await page.getByText('查看策略 JSON', { exact: true }).click()
      await expect(page.getByText('"pdf-text"', { exact: false }).first()).toBeVisible()
      await capture(page, `04-${viewport.name}-strategy-json`)
      await page.getByText('查看策略 JSON', { exact: true }).click()
      await page.getByRole('button', { name: '应用到数据集', exact: true }).click()
      await expect.poll(() => state.applies.length).toBe(1)
      await expect(page.getByText(successText, { exact: true }).first()).toBeVisible()
      await capture(page, `05-${viewport.name}-policy-applied`)
      if (await page.getByRole('dialog').isVisible()) await page.getByRole('button', { name: '关闭', exact: true }).click()

      await page.getByRole('button', { name: '生成策略', exact: true }).click()
      await expect(page.getByRole('heading', { name: '生成入库策略', exact: true })).toBeVisible()
      observations.oldSuccessVisibleOnReopen = await page.getByText(successText, { exact: true }).first().isVisible()
      await page.getByText('查看策略 JSON', { exact: true }).click()
      await page.getByRole('checkbox', { name: '覆盖已有入库策略', exact: true }).check()
      observations.checkedDialog = await page.getByRole('dialog').innerText()
      await capture(page, `06-${viewport.name}-strategy-overwrite`)
      state.failApply = '策略应用暂不可用，请稍后重试'
      await page.getByRole('button', { name: '应用到数据集', exact: true }).click()
      await expect(page.getByText(/策略应用暂不可用，请稍后重试/).first()).toBeVisible()
      await expect(page.getByRole('checkbox', { name: '覆盖已有入库策略', exact: true })).toBeChecked()
      await expect(page.getByText('"pdf-text"', { exact: false }).first()).toBeVisible()
      observations.oldSuccessVisibleAtFailure = await page.getByText(successText, { exact: true }).first().isVisible()
      const dismissalStart = Date.now()
      await expect.soft(page.getByText(successText, { exact: true }).first(), 'Previous success must leave the current failure context within Sonner exit allowance').toBeHidden({ timeout: 2000 })
      observations.oldSuccessVisibilityAfterExitAllowance = await page.getByText(successText, { exact: true }).first().isVisible()
      observations.exitObservationMs = Date.now() - dismissalStart
      await capture(page, `07-${viewport.name}-apply-failed-context`)
      state.failApply = ''
      await page.getByRole('button', { name: '应用到数据集', exact: true }).click()
      await expect.poll(() => state.applies.length).toBe(3)
      await expect(page.getByText(successText, { exact: true }).first()).toBeVisible()
      await expect(page.getByText(/策略应用暂不可用，请稍后重试/).first()).toBeHidden()
      await capture(page, `08-${viewport.name}-apply-retry-result`)
    } catch (error) {
      await capture(page, `99-${viewport.name}-interrupted`)
      throw error
    } finally {
      fs.writeFileSync(path.join(evidence, `09-${viewport.name}-fixture-state.json`), JSON.stringify({
        observations, applies: state.applies, reads: state.reads, starts: state.starts, cancels: state.cancels,
        blocked: state.base.blocked, errors: state.base.errors, url: page.url(), viewport: page.viewportSize(),
      }, null, 2))
    }
  })
}
