import { test, expect, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { snapshotFixture } from './remaining-snapshots.helpers'
import { diagnosticsFixture } from './remaining-advanced-diagnostics.helpers'
import { ablationsFixture } from './remaining-ablations.helpers'
import { similarityFixture } from './remaining-similarity.helpers'

const evidence = path.resolve(__dirname, '../../artifacts/rebrand/remaining-pages-2026-10-27/ux-advanced-final')
fs.mkdirSync(evidence, { recursive: true })

async function record(page: Page, name: string) {
  const visible = await page.locator('body').innerText()
  const fields = await page.getByRole('textbox').evaluateAll(nodes => nodes.map(node => ({ label: node.getAttribute('aria-label'), placeholder: node.getAttribute('placeholder'), value: (node as HTMLInputElement).value })))
  const numbers = await page.getByRole('spinbutton').evaluateAll(nodes => nodes.map(node => ({ label: node.getAttribute('aria-label'), placeholder: node.getAttribute('placeholder'), value: (node as HTMLInputElement).value })))
  const controls = await page.getByRole('button').evaluateAll(nodes => nodes.filter(node => (node as HTMLElement).getBoundingClientRect().width > 0).map(node => ({ text: (node as HTMLElement).innerText, label: node.getAttribute('aria-label'), disabled: (node as HTMLButtonElement).disabled })))
  const selects = await page.getByRole('combobox').evaluateAll(nodes => nodes.map(node => ({ label: node.getAttribute('aria-label'), value: (node as HTMLSelectElement).value, options: Array.from((node as HTMLSelectElement).options ?? []).map(option => ({ text: option.text, value: option.value })) })))
  const tabs = await page.getByRole('tab').allTextContents()
  const graphics = await page.locator('svg, canvas').evaluateAll(nodes => nodes.map(node => { const rect = node.getBoundingClientRect(); return { tag: node.tagName, width: rect.width, height: rect.height, rectangles: node.querySelectorAll('rect').length, label: node.getAttribute('aria-label') } }).filter(node => node.width > 100 || node.height > 100))
  const geometry = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }))
  fs.writeFileSync(path.join(evidence, `${name}.json`), JSON.stringify({ url: page.url(), visible, fields, numbers, controls, selects, tabs, graphics, geometry }, null, 2))
  await page.screenshot({ path: path.join(evidence, `${name}.png`), animations: 'disabled' })
  console.log(JSON.stringify({ name, visible, fields, numbers, controls, selects, tabs, graphics, geometry }))
}

async function openTask(page: Page, route: string) {
  await page.goto(route, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { level: 1 }).last()).toBeVisible({ timeout: 60000 })
}

async function mobile(page: Page) {
  await page.setViewportSize({ width: 390, height: 844 })
  const closeSidebar = page.getByRole('button', { name: '关闭侧边栏', exact: true })
  if (await closeSidebar.isVisible()) await page.getByRole('button', { name: '收起侧边栏', exact: true }).click()
}

test.afterEach(async ({ page }, info) => {
  if (info.status !== info.expectedStatus) await record(page, `failure-${info.title.replace(/[^a-z0-9]+/gi, '-')}`).catch(() => undefined)
})

test('open UX task snapshots compare knowledge revisions', async ({ page }) => {
  await snapshotFixture(page)
  await openTask(page, '/graph/snapshots')
  await page.getByRole('combobox').nth(0).selectOption({ label: '产品知识库' })
  await expect(page.getByRole('combobox').nth(1).locator('option')).toHaveCount(3)
  await record(page, 'snapshots-desktop-select-versions')
  await page.getByRole('combobox', { name: '快照 A', exact: true }).selectOption({ label: '历史 · version-a' })
  await page.getByRole('combobox', { name: '快照 B', exact: true }).selectOption({ label: '当前 · version-b' })
  await page.getByRole('button', { name: '开始对比', exact: true }).click()
  await expect(page.getByRole('button', { name: '复制对比结果', exact: true })).toBeEnabled({ timeout: 30000 })
  await record(page, 'snapshots-desktop-diff-result')
  await page.getByRole('button', { name: '查看变更 维护条目 01', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await record(page, 'snapshots-desktop-change-detail')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toBeHidden()
  await mobile(page)
  await record(page, 'snapshots-mobile-diff-result')
  await page.getByRole('button', { name: '选择版本', exact: true }).click()
  await record(page, 'snapshots-mobile-versions-panel')
})

test('open UX task diagnostics identify a weak question', async ({ page }) => {
  const state = await diagnosticsFixture(page)
  state.fail = false
  await openTask(page, '/graph/diagnostics')
  await page.getByRole('button', { name: '开始评测', exact: true }).click()
  await expect(page.getByText('维护周期是多久？', { exact: true })).toBeVisible({ timeout: 30000 })
  await record(page, 'diagnostics-desktop-result')
  await page.getByText('抽取质量', { exact: true }).click()
  await page.getByRole('button', { name: '读取质量报告', exact: true }).click()
  await expect(page.getByText('43', { exact: true })).toBeVisible({ timeout: 30000 })
  await record(page, 'diagnostics-desktop-quality')
  await mobile(page)
  await page.getByText('本次评测', { exact: true }).click()
  await record(page, 'diagnostics-mobile-result')
  await page.getByRole('button', { name: '评测配置', exact: true }).click()
  await record(page, 'diagnostics-mobile-config')
})

test('open UX task ablations assess the candidate configuration', async ({ page }) => {
  const state = await ablationsFixture(page)
  state.failSave = false
  await openTask(page, '/evaluations/ablations')
  await page.getByRole('button', { name: '生成对比', exact: true }).click()
  await expect(page.getByText('尚未生成运行对比', { exact: true })).toBeHidden({ timeout: 30000 })
  await expect(page.getByRole('button', { name: '生成对比', exact: true })).toBeEnabled()
  await record(page, 'ablations-desktop-comparison')
  await page.getByText('配置差异', { exact: true }).click()
  await record(page, 'ablations-desktop-config-difference')
  await page.getByRole('button', { name: '新建实验', exact: true }).click()
  await record(page, 'ablations-desktop-new-experiment')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toBeHidden()
  await mobile(page)
  await page.getByRole('button', { name: '新建实验', exact: true }).click()
  await record(page, 'ablations-mobile-new-experiment')
  await page.getByRole('button', { name: '运行消融实验', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeHidden({ timeout: 30000 })
  await expect.poll(() => state.writes.length).toBe(1)
  await page.getByRole('button', { name: '重新读取', exact: true }).click()
  await expect(page.getByRole('button', { name: '设为基线 new-verification-run', exact: true })).toBeVisible({ timeout: 30000 })
  await record(page, 'ablations-mobile-run-created-readback')
})

test('open UX task similarity inspect related sources', async ({ page }) => {
  const state = await similarityFixture(page)
  state.fail = false
  await openTask(page, '/knowledge/similarity')
  await page.getByRole('button', { name: '选择数据源', exact: true }).click()
  await record(page, 'similarity-desktop-source-form')
  await page.getByRole('combobox', { name: '横轴数据源 1', exact: true }).selectOption({ label: '设备手册（2 项）' })
  await page.getByRole('combobox', { name: '纵轴数据源 1', exact: true }).selectOption({ label: '维护规范（2 项）' })
  await page.getByRole('button', { name: '计算相似度', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeHidden({ timeout: 30000 })
  await expect(page.getByText('尚未生成相似度矩阵', { exact: true })).toBeHidden()
  await expect(page.getByRole('button', { name: '统计与详情', exact: true })).toBeEnabled()
  await expect(page.locator('svg').getByText('型号说明', { exact: true })).toBeVisible({ timeout: 60000 })
  await record(page, 'similarity-desktop-result')
  await mobile(page)
  await record(page, 'similarity-mobile-result')
  await page.getByRole('button', { name: '统计与详情', exact: true }).click()
  await record(page, 'similarity-mobile-stats')
})

test('open UX risk similarity failed calculation preserves source choices', async ({ page }) => {
  const state = await similarityFixture(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await openTask(page, '/knowledge/similarity')
  await mobile(page)
  await page.getByRole('button', { name: '选择数据源', exact: true }).click()
  await page.getByRole('combobox', { name: '横轴数据源 1', exact: true }).selectOption({ label: '设备手册（2 项）' })
  await page.getByRole('combobox', { name: '纵轴数据源 1', exact: true }).selectOption({ label: '维护规范（2 项）' })
  let releaseCalculation!: () => void
  const calculationGate = new Promise<void>(resolve => { releaseCalculation = resolve })
  await page.route('**/api/v1/ragviz/similarity/**', async route => {
    if (route.request().method() === 'POST') await calculationGate
    await route.fallback()
  })
  const calculationStarted = page.waitForRequest(request => request.url().includes('/api/v1/ragviz/similarity/') && request.method() === 'POST')
  await page.getByRole('button', { name: '计算相似度', exact: true }).click()
  await calculationStarted
  try {
    await expect(page.getByRole('button', { name: '正在计算 0/1', exact: true })).toBeDisabled()
    await record(page, 'similarity-mobile-calculation-pending')
  } finally {
    releaseCalculation()
  }
  await expect(page.getByRole('button', { name: '检查数据源', exact: true })).toBeVisible({ timeout: 30000 })
  await record(page, 'similarity-mobile-calculation-failed')
  await page.getByRole('button', { name: '检查数据源', exact: true }).click()
  await expect(page.getByRole('combobox', { name: '横轴数据源 1', exact: true })).toHaveValue('source-a')
  await expect(page.getByRole('combobox', { name: '纵轴数据源 1', exact: true })).toHaveValue('source-b')
  await record(page, 'similarity-mobile-failed-source-choices')
  state.fail = false
  await page.getByRole('button', { name: '计算相似度', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeHidden({ timeout: 30000 })
  await expect(page.getByRole('button', { name: '统计与详情', exact: true })).toBeEnabled()
  await record(page, 'similarity-mobile-recovered-result')
  await expect(page.locator('svg').getByText('型号说明', { exact: true })).toBeVisible({ timeout: 60000 })
  await record(page, 'similarity-mobile-heatmap-ready')
  await page.locator('svg text').filter({ hasText: /^1$/ }).first().click()
  await expect(page.getByRole('dialog')).toBeVisible({ timeout: 15000 })
  await expect(page.getByText('选中单元', { exact: true })).toBeVisible()
  await record(page, 'similarity-mobile-selected-cell-detail')
})

test('open UX verification ablation summary with complete response', async ({ page }) => {
  await ablationsFixture(page)
  await openTask(page, '/evaluations/ablations')
  await page.getByRole('button', { name: '生成对比', exact: true }).click()
  await expect(page.getByText('尚未生成运行对比', { exact: true })).toBeHidden({ timeout: 30000 })
  await expect(page.getByRole('button', { name: '生成对比', exact: true })).toBeEnabled()
  await record(page, 'ablations-desktop-complete-response-summary')
})

test('open UX verification stable similarity cell detail', async ({ page }) => {
  page.setDefaultTimeout(15000)
  page.setDefaultNavigationTimeout(90000)
  const state = await similarityFixture(page)
  state.fail = false
  const navigations: string[] = []
  page.on('framenavigated', frame => { if (frame === page.mainFrame()) navigations.push(frame.url()) })
  await page.setViewportSize({ width: 390, height: 844 })
  await openTask(page, '/knowledge/similarity')
  await mobile(page)
  await page.getByRole('button', { name: '选择数据源', exact: true }).click()
  await page.getByRole('combobox', { name: '横轴数据源 1', exact: true }).selectOption({ label: '设备手册（2 项）' })
  await page.getByRole('combobox', { name: '纵轴数据源 1', exact: true }).selectOption({ label: '维护规范（2 项）' })
  await page.getByRole('button', { name: '计算相似度', exact: true }).click()
  await expect(page.locator('svg').getByText('型号说明', { exact: true })).toBeVisible({ timeout: 60000 })
  await record(page, 'similarity-mobile-stable-before-cell')
  await page.locator('svg text').filter({ hasText: /^1$/ }).first().click()
  await record(page, 'similarity-mobile-stable-after-cell')
  if (!(await page.getByRole('dialog').isVisible())) await page.getByRole('button', { name: '统计与详情', exact: true }).click()
  await expect(page.getByText('选中单元', { exact: true })).toBeVisible()
  await record(page, 'similarity-mobile-stable-cell-detail')
  fs.writeFileSync(path.join(evidence, 'similarity-stable-navigations.json'), JSON.stringify(navigations, null, 2))
})

const entries = [
  { key: 'snapshots', route: '/graph/snapshots', fixture: snapshotFixture },
  { key: 'diagnostics', route: '/graph/diagnostics', fixture: diagnosticsFixture },
  { key: 'ablations', route: '/evaluations/ablations', fixture: ablationsFixture },
  { key: 'similarity', route: '/knowledge/similarity', fixture: similarityFixture },
] as const

for (const entry of entries) {
  test(`open UX initial ${entry.key}`, async ({ page }) => {
    const state = await entry.fixture(page)
    if ('fail' in state) state.fail = false
    if ('failSave' in state) state.failSave = false
    await page.setViewportSize({ width: 1600, height: 1000 })
    await page.goto(entry.route, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { level: 1 }).last()).toBeVisible({ timeout: 60000 })
    await record(page, `${entry.key}-desktop-initial`)
    await page.setViewportSize({ width: 390, height: 844 })
    await record(page, `${entry.key}-mobile-initial`)
  })
}
