import { test, expect, type Page } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { lastBatchFixture } from './remaining-last-batch.helpers'

const evidenceRoot = path.resolve(process.cwd(), '../artifacts/rebrand/remaining-pages-2026-10-27/ux-last-final')
mkdirSync(evidenceRoot, { recursive: true })
test.use({ actionTimeout: 60_000 })

async function capture(page: Page, name: string) {
  await page.screenshot({ path: path.join(evidenceRoot, `${name}.png`), fullPage: true, animations: 'disabled' })
  const visible = await page.locator('body').innerText()
  const semantics = await page.locator('body').ariaSnapshot()
  writeFileSync(path.join(evidenceRoot, `${name}.txt`), `${page.url()}\n\n${visible}\n\n${semantics}`, 'utf8')
  console.log(`UX_PAGE ${name}`)
}

test('independent chosen task - maintenance evidence', async ({ page }) => {
  test.setTimeout(600_000)
  await lastBatchFixture(page, 'light')
  for (const viewport of [{ width: 1600, height: 1000 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    const size = viewport.width === 1600 ? 'desktop' : 'mobile'
    await page.goto('/knowledge/evidence', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('textbox', { name: '检索问题', exact: true })).toBeVisible({ timeout: 60_000 })
    await page.getByRole('textbox', { name: '检索问题', exact: true }).fill('设备维护应该多久执行一次？')
    await capture(page, `${size}-evidence-question`)
    await page.getByRole('button', { name: '运行检索', exact: true }).click()
    await expect(page.getByText('维护周期为六个月，完成例行检查后记录维护日期。', { exact: true })).toBeVisible({ timeout: 60_000 })
    await capture(page, `${size}-evidence-result`)
  }
})

test('independent remaining entries and recovery observation', async ({ page }) => {
  test.setTimeout(600_000)
  await lastBatchFixture(page, 'light')
  for (const viewport of [{ width: 1600, height: 1000 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    const size = viewport.width === 1600 ? 'desktop' : 'mobile'
    if (size === 'mobile') {
      await page.goto('/knowledge/11111111-1111-4111-8111-111111111111/health', { waitUntil: 'domcontentloaded' })
      await expect(page.getByText('设备维护与操作手册.pdf').first()).toBeVisible({ timeout: 60_000 })
      await capture(page, `${size}-health-initial`)
      await page.getByRole('heading', { name: '检索命中', exact: true }).scrollIntoViewIfNeeded()
      await capture(page, `${size}-health-retrieval-section`)
    }
    await page.goto('/observability', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('30', { exact: true }).first()).toBeVisible({ timeout: 60_000 })
    await capture(page, `${size}-observability-initial`)
    await page.getByRole('tab', { name: '查询分析', exact: true }).click()
    await expect(page.getByRole('tabpanel', { name: '查询分析', exact: true })).toBeVisible({ timeout: 60_000 })
    await capture(page, `${size}-observability-query-analysis`)
    await page.getByRole('button', { name: '查看统计 query-empty-001', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 60_000 })
    await capture(page, `${size}-observability-query-detail`)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toBeHidden({ timeout: 60_000 })
    await page.goto('/knowledge/nebula', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('1 文档 · 4 切片')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('region', { name: '三维切片画布', exact: true })).toBeVisible({ timeout: 60_000 })
    await capture(page, `${size}-nebula-initial`)
    await page.getByRole('button', { name: '图例与定位', exact: true }).click()
    await expect(page.getByRole('dialog', { name: '图例与定位', exact: true })).toBeVisible({ timeout: 60_000 })
    await capture(page, `${size}-nebula-location`)
    await page.getByRole('combobox', { name: '定位切片', exact: true }).selectOption({ index: 2 })
    await capture(page, `${size}-nebula-after-selection`)
    if (await page.getByRole('dialog', { name: '图例与定位', exact: true }).isVisible()) {
      await page.getByRole('dialog', { name: '图例与定位', exact: true }).getByRole('button', { name: '完成', exact: true }).click()
    }
    await expect(page.getByText('设备维护第 2 节：每六个月进行例行检查，确认电源和润滑状态。', { exact: true })).toBeVisible({ timeout: 60_000 })
    await capture(page, `${size}-nebula-selected-chunk`)
    await page.getByRole('link', { name: '查看文档审计', exact: true }).click()
    await expect(page.getByRole('heading', { name: '文档健康审计', exact: true })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('设备维护与操作手册.pdf').first()).toBeVisible({ timeout: 60_000 })
    await capture(page, `${size}-health-from-chunk`)
    for (const auth of [
      { name: 'oidc', url: '/auth/oidc/callback' },
      { name: 'saml', url: '/auth/saml/callback?error=saml_session_missing' },
    ]) {
      await page.goto(auth.url, { waitUntil: 'domcontentloaded' })
      await expect(page.getByRole('button', { name: '返回登录', exact: true })).toBeVisible({ timeout: 60_000 })
      await capture(page, `${size}-${auth.name}-error`)
      await page.getByRole('button', { name: '返回登录', exact: true }).click()
      await expect(page).not.toHaveURL(/\/auth\/(oidc|saml)\/callback/, { timeout: 60_000 })
      await expect(page.getByRole('heading', { name: '单点登录未完成', exact: true })).toBeHidden({ timeout: 60_000 })
      await expect(page.getByRole('heading').first()).toBeVisible({ timeout: 60_000 })
      await capture(page, `${size}-${auth.name}-returned-login`)
    }
  }
})

test('independent canvas ready observation', async ({ page }) => {
  test.setTimeout(240_000)
  await lastBatchFixture(page, 'light')
  for (const viewport of [{ width: 1600, height: 1000 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    const size = viewport.width === 1600 ? 'desktop' : 'mobile'
    await page.goto('/knowledge/nebula', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('1 文档 · 4 切片')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('region', { name: '三维切片画布', exact: true }).locator('canvas')).toBeVisible({ timeout: 60_000 })
    await capture(page, `${size}-nebula-canvas-ready`)
    await page.getByRole('button', { name: '重置视角', exact: true }).click()
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
    await capture(page, `${size}-nebula-after-reset`)
  }
})
