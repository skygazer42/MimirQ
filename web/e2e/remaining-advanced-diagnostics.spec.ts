import { test, expect } from '@playwright/test'
import { openRemaining, remainingShot } from './remaining-pages.helpers'
import { diagnosticReport, diagnosticsFixture, secondDataset } from './remaining-advanced-diagnostics.helpers'
import { policyDatasetId } from './dataset-policy.helpers'

test('diagnostics retain failed configuration, expose results and reject a late dataset result', async ({ page }) => {
  const state = await diagnosticsFixture(page)
  await openRemaining(page, '/graph/diagnostics', '图谱检索评测')
  const dataset = page.getByRole('combobox', { name: '数据集', exact: true })
  await expect(dataset).toHaveValue(policyDatasetId)
  await page.getByRole('spinbutton', { name: '评测样本数', exact: true }).fill('25')
  await page.getByRole('button', { name: '开始评测', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '诊断服务暂不可用' })).toBeVisible()
  await remainingShot(page, 'after-graph-diagnostics-error')
  await expect(page.getByRole('spinbutton', { name: '评测样本数', exact: true })).toHaveValue('25')
  state.fail = false
  await page.getByRole('button', { name: '开始评测', exact: true }).click()
  await expect(page.getByRole('cell', { name: '维护周期是多久？', exact: true })).toBeVisible()
  expect(state.requests.at(-1)?.max_cases).toBe(25)
  await expect(page.getByText('已完成知识图谱检索评测', { exact: true })).toBeHidden({ timeout: 10000 })
  await remainingShot(page, 'after-graph-diagnostics-filled')
  await page.getByRole('tab', { name: '抽取质量', exact: true }).click()
  await page.getByRole('button', { name: '读取质量报告', exact: true }).click()
  await expect(page.getByText('实体数', { exact: true }).locator('..').getByRole('definition')).toHaveText('43')
  await remainingShot(page, 'after-graph-diagnostics-quality')
  let release!: () => void
  state.gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.getByRole('button', { name: '开始评测', exact: true }).click()
  await expect.poll(() => state.requests.length).toBe(3)
  await dataset.selectOption(secondDataset)
  release()
  await expect(page.getByRole('heading', { name: '尚未运行评测', exact: true })).toBeVisible()
  await expect(page.getByText('维护周期是多久？', { exact: true })).toHaveCount(0)
})

test('diagnostics exclude retrieval errors from scores and retain measured zero results', async ({
  page,
}, testInfo) => {
  await diagnosticsFixture(page)
  let includeMeasuredZero = false
  await page.route('**/api/v1/evaluations/kg/search/diagnostics', (route) =>
    route.fulfill({
      json: diagnosticReport(
        policyDatasetId,
        [
          {
            caseId: '11111111-1111-4111-8111-111111111111',
            question: '检索执行失败的样本',
            error: '检索服务不可用',
          },
          ...(includeMeasuredZero
            ? [
                {
                  caseId: '22222222-2222-4222-8222-222222222222',
                  question: '实际未命中的零分样本',
                },
              ]
            : []),
        ],
        'diagnostic-run-1',
      ),
    }),
  )
  await openRemaining(page, '/graph/diagnostics', '图谱检索评测')
  await page.getByRole('button', { name: '开始评测', exact: true }).click()
  const errorRow = page.getByRole('row').filter({ hasText: '检索执行失败的样本' })
  await expect(errorRow.getByRole('cell', { name: '检索失败 检索服务不可用', exact: true })).toBeVisible()
  await expect(errorRow.getByRole('cell', { name: '—', exact: true })).toHaveCount(2)
  await expect(page.getByText('Baseline MRR', { exact: true }).locator('..').getByRole('definition')).toHaveText('-')
  await expect(page.getByText('诊断包含检索失败样本', { exact: true })).toBeVisible()

  includeMeasuredZero = true
  await page.getByRole('button', { name: '开始评测', exact: true }).click()
  const measuredRow = page.getByRole('row').filter({ hasText: '实际未命中的零分样本' })
  await expect(measuredRow.getByRole('cell', { name: '未命中', exact: true })).toBeVisible()
  await expect(measuredRow.getByRole('cell', { name: '0', exact: true })).toHaveCount(2)
  await expect(errorRow.getByRole('cell', { name: '—', exact: true })).toHaveCount(2)
  await page.screenshot({ path: testInfo.outputPath('errors-and-measured-zero.png'), fullPage: true })
  await page.getByRole('button', { name: '得分分布', exact: true }).click()
  await expect(page.getByText('0.0–0.2', { exact: true }).locator('..').getByText('1', { exact: true })).toBeVisible()
})

for (const variant of [
  { name: 'narrow-dark', width: 1120, height: 850, theme: 'dark' as const },
  { name: 'phone', width: 390, height: 844, theme: 'light' as const },
]) {
  test(`diagnostics ${variant.name} configuration and reader remain usable`, async ({ page }) => {
    const state = await diagnosticsFixture(page, variant.theme)
    await page.setViewportSize(variant)
    await openRemaining(page, '/graph/diagnostics', '图谱检索评测')
    if (variant.name === 'phone') await page.getByRole('button', { name: '评测配置', exact: true }).click()
    await expect(page.getByRole('spinbutton', { name: '评测样本数', exact: true })).toBeVisible()
    const heading = (await page.getByRole('heading', { name: '图谱检索评测', exact: true }).boundingBox())!
    const runButton = (await page.getByRole('button', { name: '开始评测', exact: true }).boundingBox())!
    expect(runButton.y).toBeLessThan(heading.y + heading.height + 24)
    const input = page.getByRole('spinbutton', { name: '评测样本数', exact: true })
    if (variant.name === 'phone') {
      expect(
        await input.evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize)),
      ).toBeGreaterThanOrEqual(16)
    }
    await remainingShot(page, `after-graph-diagnostics-${variant.name}`)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    if (variant.name === 'phone') await page.getByRole('button', { name: '报告结果', exact: true }).click()
    await expect(page.getByRole('heading', { name: '尚未运行评测', exact: true })).toBeVisible()
    await remainingShot(page, `after-graph-diagnostics-${variant.name}-empty`)
    state.fail = false
    let release!: () => void
    state.gate = new Promise<void>((resolve) => {
      release = resolve
    })
    await page.getByRole('button', { name: '开始评测', exact: true }).click()
    try {
      await expect(page.getByRole('status').filter({ hasText: /^正在评测…$/ })).toBeVisible()
      await expect(page.getByRole('button', { name: '正在评测…', exact: true })).toBeDisabled()
      const pendingBounds = (await page.getByRole('button', { name: '正在评测…', exact: true }).boundingBox())!
      expect(Math.abs(pendingBounds.y - runButton.y)).toBeLessThanOrEqual(1)
      await remainingShot(page, `after-graph-diagnostics-${variant.name}-loading`)
    } finally {
      release()
    }
    await expect(page.getByRole('cell', { name: '维护周期是多久？', exact: true })).toBeVisible()
    await expect(page.getByText('已完成知识图谱检索评测', { exact: true })).toBeHidden({ timeout: 10000 })
    await remainingShot(page, `after-graph-diagnostics-${variant.name}-report`)
    if (variant.name === 'phone') {
      const table = page.getByRole('region', { name: '评测样本结果', exact: true })
      await table.evaluate((element) => {
        element.scrollLeft = element.scrollWidth
      })
      await expect(page.getByRole('columnheader', { name: 'MRR', exact: true })).toBeInViewport()
    }
    await page.getByRole('tab', { name: '抽取质量', exact: true }).click()
    await page.getByRole('button', { name: '读取质量报告', exact: true }).click()
    await expect(page.getByText('实体数', { exact: true }).locator('..').getByRole('definition')).toHaveText('43')
    const average = page.getByText('平均每实体关系数', { exact: true }).locator('..').getByRole('definition')
    await expect(average).toHaveText('1.907')
    expect(await average.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
    await remainingShot(page, `after-graph-diagnostics-${variant.name}-quality`)
    const identifier = page.getByRole('definition').filter({ hasText: policyDatasetId })
    await expect(identifier).toHaveCount(1)
    expect(await identifier.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
    await expect(page.getByText('关系边已截断', { exact: true }).locator('..').getByRole('definition')).toHaveText('否')
    await identifier.scrollIntoViewIfNeeded()
    await remainingShot(page, `after-graph-diagnostics-${variant.name}-quality-scope`)
    const rawReport = page.getByText('完整质量报告', { exact: true })
    await rawReport.click()
    await expect(rawReport.locator('..').locator('pre')).toContainText(String(82 / 43))
    await page.getByRole('tab', { name: '运行历史与比较', exact: true }).click()
    await expect(page.getByRole('heading', { name: '当前数据集暂无运行记录', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '上一页', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '下一页', exact: true })).toHaveCount(0)
    await remainingShot(page, `after-graph-diagnostics-${variant.name}-history`)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  })
}
