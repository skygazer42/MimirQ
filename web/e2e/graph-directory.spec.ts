import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'
import { installCommonApiMocks, installDeterministicRandom } from './enterprise-quality-telemetry.helpers'

const evidence = path.resolve(__dirname, '../../artifacts/rebrand/graph-directory-v1/tests')
const facts = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../public/brand/explorations/graph-layouts-v1/facts.json'), 'utf8')) as {
  nodes: Array<{ id: string; label: string; type: string }>
  edges: Array<{ source: string; target: string; label: string }>
}
const ids = new Map(facts.nodes.map((node, i) => [node.id, `72000000-0000-4000-8000-${String(i + 1).padStart(12, '0')}`]))
const selectedId = ids.get('architecture')!
const typeNames: Record<string, string> = { role: '角色', ability: '能力', practice: '行为', asset: '资产', outcome: '目标' }
const directory = (page: Page) => page.locator('[data-graph-directory]')
const selected = (page: Page) => directory(page).locator(`[data-directory-node="${selectedId}"]`)

async function json(route: Route, body: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }) }
async function fixture(page: Page, options: { empty?: boolean } = {}) {
  await installCommonApiMocks(page, { uploaded: false })
  await installDeterministicRandom(page)
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.addInitScript(() => {
    localStorage.setItem('theme', 'light')
    localStorage.setItem('mimirq.surfaceTheme', 'ocean')
    localStorage.setItem('mimirq.themeColor', '#20262e')
    document.addEventListener('DOMContentLoaded', () => { const style = document.createElement('style'); style.textContent = 'nextjs-portal { display: none !important; }'; document.head.appendChild(style) }, { once: true })
  })
  const nodes = facts.nodes.map(node => ({ id: ids.get(node.id)!, label: node.label, meta: { kind: 'entity', type: typeNames[node.type], aliases: node.id === 'architecture' ? ['D2'] : [], description: node.id === 'architecture' ? '从端到端视角设计系统架构，把握技术选型、模块边界与技术债务。' : '' } }))
  nodes.push({ id: 'isolated', label: '独立实体', meta: { kind: 'entity', type: '其他', aliases: [], description: '' } })
  nodes.push({ id: 'event-1', label: '架构评审记录', meta: { kind: 'event', type: '事件', aliases: [], description: '' } })
  const links = facts.edges.map((edge, i) => ({ source: ids.get(edge.source)!, target: ids.get(edge.target)!, label: edge.label, meta: { kind: 'entity_relation', predicate: edge.label, confidence: 0.93 }, id: `link-${i}` }))
  links.push({ source: 'event-1', target: selectedId, label: '涉及', meta: { kind: 'event_entity', predicate: '涉及', confidence: 1 }, id: 'event-link' })
  const state = { empty: Boolean(options.empty), reads: 0, writes: [] as string[], errors: [] as string[] }
  page.on('pageerror', error => state.errors.push(error.message))
  await page.route('**/api/v1/kg/**', async route => {
    const request = route.request(); const url = new URL(request.url())
    if (request.method() !== 'GET') state.writes.push(url.pathname)
    if (url.pathname === '/api/v1/kg/graph') { state.reads++; return json(route, state.empty ? { nodes: [], links: [] } : { nodes, links }) }
    if (url.pathname === '/api/v1/kg/stats') return json(route, { entities: 19, events: 1, links: links.length, entity_types: [] })
    if (url.pathname.endsWith('/aliases')) return json(route, { entity_id: selectedId, items: [] })
    if (url.pathname.endsWith('/alias_suggestions')) return json(route, { entity_id: selectedId, items: [] })
    if (url.pathname.includes('/entities/')) {
      const id = url.pathname.split('/entities/')[1].split('/')[0]
      const node = nodes.find(item => item.id === id) || nodes[2]
      return json(route, { entity: { id, name: node.label, normalized_name: node.label, type: node.meta.type, description: node.meta.description }, events: [{ id: 'event-1', title: '能力贡献项详解', summary: '工程能力标准', content: '系统架构设计包含技术选型与系统边界。', document_id: 'source-document', chunk_id: 'source-chunk' }], neighbors: [], stats: {} })
    }
    if (url.pathname.includes('/events/')) return json(route, { event: { id: 'event-1', title: '架构评审记录', summary: '工程能力标准', content: '架构评审内容', document_id: 'source-document' }, entities: [] })
    return json(route, { items: [], nodes: [], links: [] })
  })
  return state
}
async function open(page: Page) {
  await page.goto('/graph', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-graph-directory-page]')).toBeVisible({ timeout: 60_000 })
  await expect(selected(page)).toBeVisible({ timeout: 30_000 })
}
async function noOverflow(page: Page) { expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1) }
async function graphReady(page: Page) {
  const renderer = page.locator('[data-graph-renderer]').filter({ visible: true })
  await expect(renderer).toHaveAttribute('aria-busy', 'false', { timeout: 45_000 })
  await expect(renderer.locator('canvas').first()).toBeVisible()
}

test('B directory searches aliases, focuses one or two hops and restores the full graph without hiding the directory', async ({ page }) => {
  const state = await fixture(page); await open(page)
  await expect(directory(page).locator('[data-directory-node]')).toHaveCount(20)
  await expect(directory(page).getByText('事件', { exact: true })).toBeVisible()
  await page.getByRole('searchbox', { name: '搜索图谱实体', exact: true }).fill('d2')
  await expect(directory(page).locator('[data-directory-node]')).toHaveCount(1)
  await selected(page).click()
  await expect(page.locator('[data-graph-selection]')).toContainText('6 个直接关联')
  await expect(page.getByRole('region', { name: '图谱节点详情', exact: true })).toBeHidden()
  await expect(page.locator('footer')).toContainText('7 节点')
  await expect(page.getByRole('button', { name: '聚焦实体', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await graphReady(page)
  const graphBounds = await page.getByRole('region', { name: '知识图谱画布', exact: true }).boundingBox()
  const summaryBounds = await page.locator('[data-graph-selection]').boundingBox()
  expect(graphBounds!.y + graphBounds!.height).toBeLessThanOrEqual(summaryBounds!.y + 1)
  await page.screenshot({ path: `${evidence}/desktop-focused.png` })
  await page.getByRole('combobox', { name: '邻域展开层数' }).click()
  await page.getByRole('option', { name: '展开 2 层', exact: true }).click()
  await expect(page.locator('footer')).not.toContainText('7 节点')
  await page.getByRole('button', { name: '返回完整图谱', exact: true }).click()
  await expect(page.locator('footer')).toContainText('20 节点')
  await expect(page.getByRole('searchbox', { name: '搜索图谱实体', exact: true })).toHaveValue('d2')
  await page.getByRole('searchbox', { name: '搜索图谱实体', exact: true }).fill('')
  await noOverflow(page)
  try {
    await graphReady(page)
  } finally {
    fs.mkdirSync(evidence, { recursive: true })
    fs.writeFileSync(`${evidence}/render-diagnostics.json`, JSON.stringify({ errors: state.errors, dom: await page.locator('[data-graph-canvas-zone]').evaluate(element => ({ text: element.textContent, children: [...element.children].map(child => ({ tag: child.tagName, cls: child.className, box: { width: child.getBoundingClientRect().width, height: child.getBoundingClientRect().height } })), canvases: [...element.querySelectorAll('canvas')].map(canvas => ({ width: canvas.width, height: canvas.height })) })) }, null, 2))
  }
  await page.screenshot({ path: `${evidence}/desktop-b.png` })
  expect(state.writes).toEqual([])
})

test('phone switches directory and graph while retaining search, selection and keyboard search access', async ({ page }) => {
  await fixture(page); await page.setViewportSize({ width: 390, height: 844 }); await open(page)
  await page.getByRole('searchbox', { name: '搜索图谱实体', exact: true }).fill('D2')
  await selected(page).click()
  await expect(page.getByRole('button', { name: '关系图谱', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('[data-graph-selection]')).toBeVisible()
  await graphReady(page)
  await page.screenshot({ path: `${evidence}/phone-graph.png` })
  await page.getByRole('button', { name: '实体目录', exact: true }).click()
  await expect(page.getByRole('searchbox', { name: '搜索图谱实体', exact: true })).toHaveValue('D2')
  await expect(selected(page)).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: '关系图谱', exact: true }).click()
  await page.keyboard.press('Control+f')
  await expect(page.getByRole('searchbox', { name: '搜索图谱实体', exact: true })).toBeFocused()
  await noOverflow(page)
  await page.screenshot({ path: `${evidence}/phone-directory.png` })
})

test('path discovery can select its endpoints from the full directory and return to the focused object', async ({ page }) => {
  await fixture(page); await open(page); await selected(page).click()
  await page.getByRole('button', { name: '路径发现', exact: true }).click()
  await expect(page.locator('footer')).toContainText('20 节点')
  await selected(page).click()
  await directory(page).locator(`[data-directory-node="${ids.get('delivery')}"]`).click()
  await expect(page.getByText('路径分析完成', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '退出路径分析', exact: true }).click()
  await expect(page.getByRole('button', { name: '聚焦实体', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('[data-graph-selection]')).toContainText('系统架构设计')
})

test('node details, analysis, 3D and export controls remain reachable and follow the dark surface', async ({ page }) => {
  const state = await fixture(page); await open(page); await selected(page).click()
  await page.getByRole('button', { name: '查看详情与来源', exact: true }).click()
  await expect(page.getByRole('region', { name: '图谱节点详情' })).toBeVisible()
  await page.getByRole('button', { name: '关闭详情面板', exact: true }).click()
  await expect(page.locator('[data-graph-selection]')).toBeVisible()
  await expect(page.getByRole('button', { name: '查看详情与来源', exact: true })).toBeFocused()
  await page.getByRole('button', { name: '网络分析', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '网络分析', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '拖动图谱统计栏', exact: true })).toBeHidden()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '更多画布工具', exact: true }).click()
  await page.getByRole('button', { name: '切换至 3D 空间', exact: true }).click()
  await graphReady(page)
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '导出图谱图片', exact: true }).click()
  await expect(page.getByRole('button', { name: '下载 PNG', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '切换主题', exact: true }).click()
  await page.getByRole('menuitem', { name: /深色|暗色/ }).click()
  await expect.poll(() => page.locator('[data-graph-directory-page]').evaluate(element => { const rgb = getComputedStyle(element).backgroundColor.match(/\d+/g)?.map(Number) || []; return rgb.slice(0, 3).every(value => value < 80) })).toBe(true)
  await noOverflow(page)
  await page.screenshot({ path: `${evidence}/dark-b.png` })
  expect(state.writes).toEqual([])
})

test('empty graph retains a usable scope picker without showing illustrative nodes', async ({ page }) => {
  const state = await fixture(page, { empty: true })
  await page.goto('/graph', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-graph-directory-page]')).toBeVisible({ timeout: 60_000 })
  await expect(directory(page).getByText('当前范围没有节点', { exact: true })).toBeVisible()
  await expect(directory(page).locator('[data-directory-node]')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '网络分析', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '选择图谱', exact: true }).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await page.screenshot({ path: `${evidence}/empty-b.png` })
  expect(state.writes).toEqual([])
})

test('type filters update the directory and the current graph counts, then clear back to the loaded scope', async ({ page }) => {
  const state = await fixture(page); await open(page)
  await page.getByRole('button', { name: /^筛选/ }).click()
  await page.getByRole('checkbox', { name: '能力 5', exact: true }).click()
  await expect(directory(page).locator('[data-directory-node]')).toHaveCount(2)
  await expect(page.locator('footer')).toContainText('2 节点')
  await expect(page.locator('footer')).toContainText('2 个节点符合筛选')
  await page.getByRole('button', { name: '清除', exact: true }).click()
  await expect(directory(page).locator('[data-directory-node]')).toHaveCount(20)
  await expect(page.locator('footer')).toContainText('20 节点')
  await expect(page.locator('footer')).toContainText('7 种类型')
  expect(state.writes).toEqual([])
})
