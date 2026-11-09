import { test, expect } from '@playwright/test'
import { ablationsFixture } from './remaining-ablations.helpers'
import { openRemaining, remainingShot } from './remaining-pages.helpers'

for (const variant of [{ name: 'desktop', width: 1600, height: 1000, theme: 'light' as const }, { name: 'narrow-dark', width: 1120, height: 850, theme: 'dark' as const }, { name: 'phone', width: 390, height: 844, theme: 'light' as const }]) {
  test(`ablations ${variant.name} keeps failed parameters and reads back a submitted run`, async ({ page }) => {
    test.setTimeout(300000)
    const state = await ablationsFixture(page, variant.theme)
    await page.setViewportSize(variant)
    await openRemaining(page, '/evaluations/ablations', '检索调参对比')
    await expect(page.getByRole('combobox', { name: '实验数据集', exact: true })).toHaveValue('4bf314df-47e7-4594-b611-666666666666')
    await expect(page.getByRole('table', { name: '实验运行', exact: true }).getByRole('row')).toHaveCount(3)
    await remainingShot(page, `after-retrieval-ablations-${variant.name}`)
    await page.getByRole('button', { name: '新建实验', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '实验参数', exact: true })
    const cases = dialog.getByRole('spinbutton', { name: '评测样本上限', exact: true })
    await cases.fill('25')
    await remainingShot(page, `after-retrieval-ablations-config-${variant.name}`)
    await expect(dialog.getByRole('button', { name: '运行消融实验', exact: true })).toBeEnabled()
    await dialog.getByRole('button', { name: '运行消融实验', exact: true }).click()
    await expect(dialog.getByRole('alert').filter({ hasText: '实验提交暂不可用' })).toBeVisible()
    await expect(cases).toHaveValue('25')
    expect(state.writes[0].max_cases).toBe(25)
    state.failSave = false
    await dialog.getByRole('button', { name: '运行消融实验', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(page.getByRole('table', { name: '实验运行', exact: true }).getByRole('row')).toHaveCount(4)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  })
}

test('older leaderboard runs remain visible and can be compared outside the recent run window', async ({ page }) => {
  const state = await ablationsFixture(page)
  state.includeOlder = true
  await openRemaining(page, '/evaluations/ablations', '检索调参对比')
  await expect(page.getByRole('combobox', { name: '实验数据集', exact: true })).toHaveValue('4bf314df-47e7-4594-b611-666666666666')
  await page.getByRole('button', { name: '按指标排行', exact: true }).click()
  const table = page.getByRole('table', { name: '实验运行', exact: true })
  await expect(table.getByRole('row')).toHaveCount(4)
  await table.getByRole('button', { name: '设为候选 archived-best-run', exact: true }).click()
  await expect.poll(() => state.detailReads).toEqual(['archived-best-run'])
  await table.getByRole('button', { name: '设为基线 baseline-run', exact: true }).click()
  await page.getByRole('button', { name: '生成对比', exact: true }).click()
  await expect.poll(() => state.diffs.at(-1)).toEqual({ target: 'archived-best-run', base: 'baseline-run' })
})

test('a later comparison selector cancels an older ranking detail selection', async ({ page }) => {
  const state = await ablationsFixture(page)
  state.includeOlder = true
  let release!: () => void
  state.detailGate = new Promise<void>(resolve => { release = resolve })
  await openRemaining(page, '/evaluations/ablations', '检索调参对比')
  await expect(page.getByRole('combobox', { name: '实验数据集', exact: true })).toHaveValue('4bf314df-47e7-4594-b611-666666666666')
  await page.getByRole('button', { name: '按指标排行', exact: true }).click()
  await page.getByRole('button', { name: '设为候选 archived-best-run', exact: true }).click()
  await expect.poll(() => state.detailReads.length).toBe(1)
  const selector = page.getByRole('combobox', { name: '选择候选运行', exact: true })
  await selector.click()
  await page.getByRole('option').filter({ hasText: /baseline/ }).click()
  await expect(selector).toContainText('baseline')
  const response = page.waitForResponse(value => new URL(value.url()).pathname.endsWith('/runs/archived-best-run'))
  release()
  await (await response).finished()
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await expect(selector).toContainText('baseline')
  await page.getByRole('button', { name: '生成对比', exact: true }).click()
  await expect.poll(() => state.diffs.at(-1)?.target).toBe('baseline-run')
})
