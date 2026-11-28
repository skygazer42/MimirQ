import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'
import type { EnterpriseOntologyDocumentGraph, EnterpriseOntologyGraphEdit } from '../types/enterprise-ontology'
import { installCommonApiMocks, installDeterministicRandom } from './enterprise-quality-telemetry.helpers'

const facts = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, '../public/brand/explorations/graph-layouts-v1/facts.json'), 'utf8'),
) as {
  nodes: Array<{ id: string; label: string; type: string }>
  edges: Array<{ source: string; target: string; label: string }>
}
const ids = new Map(
  facts.nodes.map((node, i) => [node.id, `72000000-0000-4000-8000-${String(i + 1).padStart(12, '0')}`]),
)
const selectedId = ids.get('architecture')!
const typeNames: Record<string, string> = {
  role: '角色',
  ability: '能力',
  practice: '行为',
  asset: '资产',
  outcome: '目标',
}
const directory = (page: Page) => page.locator('[data-graph-directory]')
const selected = (page: Page) => directory(page).locator(`[data-directory-node="${selectedId}"]`)

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}
async function fixture(page: Page, options: { empty?: boolean } = {}) {
  await installCommonApiMocks(page, { uploaded: false })
  await page.route('**/api/v1/meta/details', (route) => json(route, { features: { kg_enabled: true } }))
  await installDeterministicRandom(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.addInitScript(() => {
    localStorage.setItem('theme', 'light')
    localStorage.setItem('mimirq.surfaceTheme', 'ocean')
    localStorage.removeItem('mimirq.themeColor')
    document.addEventListener(
      'DOMContentLoaded',
      () => {
        const style = document.createElement('style')
        style.textContent = 'nextjs-portal { display: none !important; }'
        document.head.appendChild(style)
      },
      { once: true },
    )
  })
  const nodes = facts.nodes.map((node) => ({
    id: ids.get(node.id)!,
    label: node.label,
    meta: {
      kind: 'entity',
      type: typeNames[node.type],
      aliases: node.id === 'architecture' ? ['D2'] : [],
      description: node.id === 'architecture' ? '从端到端视角设计系统架构，把握技术选型、模块边界与技术债务。' : '',
    },
  }))
  nodes.push({
    id: 'isolated',
    label: '独立实体',
    meta: { kind: 'entity', type: '其他', aliases: [], description: '' },
  })
  nodes.push({
    id: 'event-1',
    label: '架构评审记录',
    meta: { kind: 'event', type: '事件', aliases: [], description: '' },
  })
  const links = facts.edges.map((edge, i) => ({
    source: ids.get(edge.source)!,
    target: ids.get(edge.target)!,
    label: edge.label,
    meta: { kind: 'entity_relation', predicate: edge.label, confidence: 0.93 },
    id: `link-${i}`,
  }))
  links.push({
    source: 'event-1',
    target: selectedId,
    label: '涉及',
    meta: { kind: 'event_entity', predicate: '涉及', confidence: 1 },
    id: 'event-link',
  })
  const state = {
    empty: Boolean(options.empty),
    failRead: false,
    reads: 0,
    writes: [] as string[],
    errors: [] as string[],
  }
  page.on('pageerror', (error) => state.errors.push(error.message))
  await page.route('**/api/v1/kg/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() !== 'GET') state.writes.push(url.pathname)
    if (url.pathname === '/api/v1/kg/graph') {
      state.reads++
      if (state.failRead) return json(route, { detail: '图谱读取暂时不可用' }, 503)
      return json(route, state.empty ? { nodes: [], links: [] } : { nodes, links })
    }
    if (url.pathname === '/api/v1/kg/stats')
      return json(route, { entities: 19, events: 1, links: links.length, entity_types: [] })
    if (url.pathname.endsWith('/aliases')) return json(route, { entity_id: selectedId, items: [] })
    if (url.pathname.endsWith('/alias_suggestions')) return json(route, { entity_id: selectedId, items: [] })
    if (url.pathname.includes('/entities/')) {
      const id = url.pathname.split('/entities/')[1].split('/')[0]
      const node = nodes.find((item) => item.id === id) || nodes[2]
      return json(route, {
        entity: {
          id,
          name: node.label,
          normalized_name: node.label,
          type: node.meta.type,
          description: node.meta.description,
        },
        events: [
          {
            id: 'event-1',
            title: '能力贡献项详解',
            summary: '工程能力标准',
            content: '系统架构设计包含技术选型与系统边界。',
            document_id: 'source-document',
            chunk_id: 'source-chunk',
          },
        ],
        neighbors: [],
        stats: {},
      })
    }
    if (url.pathname.includes('/events/'))
      return json(route, {
        event: {
          id: 'event-1',
          title: '架构评审记录',
          summary: '工程能力标准',
          content: '架构评审内容',
          document_id: 'source-document',
        },
        entities: [],
      })
    return json(route, { items: [], nodes: [], links: [] })
  })
  return state
}
async function open(page: Page) {
  await page.goto('/graph', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-graph-directory-page]')).toBeVisible({ timeout: 60_000 })
  await expect(selected(page)).toBeVisible({ timeout: 30_000 })
}
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
}
async function graphReady(page: Page) {
  const renderer = page.locator('[data-graph-renderer]').filter({ visible: true })
  await renderer.evaluate(
    () => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))),
  )
  await expect(renderer).toHaveAttribute('aria-busy', 'false', { timeout: 45_000 })
  await expect(renderer.locator('canvas').first()).toBeVisible()
}

test('corrects ontology entities and relationships from the main graph', async ({ page }) => {
  await fixture(page, { empty: true })
  const datasetId = '11000000-0000-4000-8000-000000000001'
  const documentId = '11000000-0000-4000-8000-000000000002'
  const versionId = '11000000-0000-4000-8000-000000000003'
  const chunkId = '11000000-0000-4000-8000-000000000004'
  const source = '工单 WO-01 归属设备 E-102。'
  const span = (quote: string) => ({
    quote,
    start_char: source.indexOf(quote),
    end_char: source.indexOf(quote) + quote.length,
    source: 'quote',
  })
  const graph: EnterpriseOntologyDocumentGraph = {
    version_id: versionId,
    version_number: 1,
    pipeline_hash: 'test-pipeline',
    revision: '1'.repeat(64),
    can_edit: true,
    corrected: false,
    chunks: [{ id: chunkId, page: 3, index: 0 }],
    source_text: source,
    object_types: {
      work_order: {
        label: '工单',
        key: ['id'],
        properties: { id: { type: 'string', multiple: false, required: true } },
      },
      equipment: {
        label: '设备',
        key: ['id'],
        properties: { id: { type: 'string', multiple: false, required: true } },
      },
    },
    relations: {
      order_for_equipment: { label: '归属设备', from: 'work_order', to: 'equipment', cardinality: 'many_to_one' },
    },
    chunk: {
      document_id: documentId,
      chunk_id: chunkId,
      page: 3,
      entities: [
        {
          id: 'order',
          name: 'WO-01',
          object_type: 'work_order',
          evidence: span('工单 WO-01'),
          business_key: null,
          identity_status: 'unresolved',
        },
        {
          id: 'equipment',
          name: 'E-102',
          object_type: 'equipment',
          evidence: span('设备 E-102'),
          business_key: null,
          identity_status: 'unresolved',
        },
      ],
      relations: [
        { subject_id: 'order', object_id: 'equipment', predicate: 'order_for_equipment', evidence: span(source) },
      ],
    },
  }
  let stored = graph
  const writes: EnterpriseOntologyGraphEdit[] = []
  await page.route('**/api/v1/observability/frontend-vitals', (route) => route.fulfill({ status: 204 }))
  await page.route(/\/api\/v1\/documents\/?\?/, (route) => {
    if (new URL(route.request().url()).searchParams.get('dataset_id') !== datasetId) return route.fallback()
    return json(route, { items: [{ id: documentId, filename: '维修制度.pdf', status: 'completed' }], total: 1 })
  })
  const path = `/api/v1/kg/ontologies/datasets/${datasetId}`
  const occurrenceId = (entityId: string) => `ontology-${entityId}`
  const provenance = { ontology_version_id: versionId, document_id: documentId, chunk_id: chunkId, page: 3 }
  await page.route(/\/api\/v1\/kg\/graph\?/, (route) => {
    const params = new URL(route.request().url()).searchParams
    expect(params.get('dataset_id')).toBe(datasetId)
    expect(params.get('prefer_ontology')).toBe('true')
    return json(route, {
      stats: { ontology_version_id: versionId },
      nodes: stored.chunk.entities?.map((entity) => ({
        id: occurrenceId(entity.id),
        label: entity.name,
        meta: { ...provenance, kind: 'entity', type: entity.object_type, ontology_entity_id: entity.id },
      })),
      links: stored.chunk.relations?.map((relation) => ({
        source: occurrenceId(relation.subject_id),
        target: occurrenceId(relation.object_id),
        label: relation.predicate,
        meta: {
          ...provenance,
          id: 'ontology-relation',
          kind: 'entity_relation',
          predicate: relation.predicate,
          ontology_subject_id: relation.subject_id,
          ontology_object_id: relation.object_id,
          evidence: relation.evidence,
        },
      })),
    })
  })
  const graphReads: string[] = []
  await page.route('**' + path + '/**', async (route) => {
    const request = route.request()
    if (request.method() === 'GET') {
      const url = new URL(request.url())
      expect(url.pathname).toBe(path + `/documents/${documentId}/graph`)
      graphReads.push(url.searchParams.get('chunk_id') ?? '')
      return json(route, stored)
    }
    expect(new URL(request.url()).pathname).toBe(path + `/documents/${documentId}/graph/${chunkId}`)
    const body = request.postDataJSON() as EnterpriseOntologyGraphEdit
    expect(body.expected_revision).toBe(stored.revision)
    expect(body.version_id).toBe(versionId)
    writes.push(body)
    if (writes.length === 1) return json(route, { detail: '图谱或原文已更新' }, 409)
    stored = {
      ...graph,
      revision: String(writes.length).repeat(64),
      corrected: body.graph !== null,
      chunk: body.graph
        ? {
            ...graph.chunk,
            entities: body.graph.entities.map((item) => ({
              ...item,
              business_key: null,
              identity_status: 'unresolved',
            })),
            relations: body.graph.relations,
          }
        : graph.chunk,
    }
    return json(route, stored)
  })

  await page.goto(`/graph?dataset_id=${datasetId}`, { waitUntil: 'domcontentloaded' })
  const dialog = page.getByRole('dialog', { name: '本体图谱', exact: true })
  const equipment = directory(page).locator(`[data-directory-node="${occurrenceId('equipment')}"]`)
  const openEquipment = async () => {
    await equipment.click()
    await page.getByRole('button', { name: '查看与修正实体' }).click()
  }
  await openEquipment()
  await expect(dialog.getByLabel('实体名称')).toHaveValue('E-102')
  await expect(dialog.getByLabel('分块原文')).toHaveValue(source)
  expect(graphReads).toEqual([chunkId])
  const changeName = async () => {
    await dialog.getByLabel('实体名称').fill('设备')
    await dialog.getByRole('button', { name: '应用实体修改' }).click()
  }
  await changeName()
  await dialog.getByRole('button', { name: '保存图谱修正' }).click()
  await expect(dialog.getByRole('alert')).toContainText('图谱或原文已更新')
  await dialog.getByRole('button', { name: '放弃本次修改并重新加载' }).click()
  await expect(dialog.getByRole('alert')).toHaveCount(0)
  await dialog.getByRole('combobox', { name: '选择实体' }).selectOption('equipment')
  await changeName()
  await dialog.getByRole('button', { name: '保存图谱修正' }).click()
  await expect(dialog.getByRole('status')).toHaveText('图谱修正已保存')
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(equipment).toHaveAttribute('title', '设备')
  expect(writes[1].graph?.entities.find((item) => item.id === 'equipment')?.name).toBe('设备')

  await graphReady(page)
  await page.locator('[data-graph-renderer] canvas').filter({ visible: true }).first().click()
  await page.getByRole('button', { name: '查看与修正关系' }).click()
  await expect(dialog.getByRole('tab', { name: '关系' })).toHaveAttribute('aria-selected', 'true')
  await expect(dialog.getByLabel('关系证据')).toHaveValue(source)
  await dialog.getByRole('button', { name: '移除关系' }).click()
  await dialog.getByRole('button', { name: '保存图谱修正' }).click()
  await expect(dialog.getByRole('status')).toHaveText('图谱修正已保存')
  expect(writes[2].graph?.relations).toEqual([])
  await dialog.screenshot({ path: test.info().outputPath('ontology-graph-correction.png'), animations: 'disabled' })
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(page.locator('footer')).toContainText('0 关系')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await openEquipment()
  await expect(dialog.getByText('已人工修正')).toBeVisible()
  await expect(dialog.getByLabel('实体名称')).toHaveValue('设备')
  await expect(dialog.getByLabel('实体名称')).toBeInViewport()
  await noOverflow(page)
  const bounds = await dialog.boundingBox()
  expect(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 391).toBeTruthy()
  await dialog.screenshot({ path: test.info().outputPath('ontology-graph-phone.png'), animations: 'disabled' })
  await dialog.getByRole('button', { name: '恢复模型抽取' }).click()
  await expect(dialog.getByRole('status')).toHaveText('已恢复模型抽取结果')
  expect(writes[3].graph).toBeNull()
  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(page.locator('footer')).toContainText('1 关系')
})

test('B directory searches aliases, focuses one or two hops and restores the full graph without hiding the directory', async ({
  page,
}) => {
  const state = await fixture(page)
  await open(page)
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
  await page.screenshot({ path: test.info().outputPath('desktop-focused.png') })
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
    fs.writeFileSync(
      test.info().outputPath('render-diagnostics.json'),
      JSON.stringify(
        {
          errors: state.errors,
          dom: await page.locator('[data-graph-canvas-zone]').evaluate((element) => ({
            text: element.textContent,
            children: [...element.children].map((child) => ({
              tag: child.tagName,
              cls: child.className,
              box: { width: child.getBoundingClientRect().width, height: child.getBoundingClientRect().height },
            })),
            canvases: [...element.querySelectorAll('canvas')].map((canvas) => ({
              width: canvas.width,
              height: canvas.height,
            })),
          })),
        },
        null,
        2,
      ),
    )
  }
  await page.screenshot({ path: test.info().outputPath('desktop-b.png') })
  expect(state.writes).toEqual([])
})

test('phone switches directory and graph while retaining search, selection and keyboard search access', async ({
  page,
}) => {
  await fixture(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await open(page)
  const titleBounds = (await page.getByRole('heading', { name: '知识图谱', exact: true }).boundingBox())!
  const navigationBounds = (await page.getByRole('button', { name: '展开侧边栏', exact: true }).boundingBox())!
  expect(titleBounds.x).toBeGreaterThanOrEqual(navigationBounds.x + navigationBounds.width + 8)
  await page.getByRole('searchbox', { name: '搜索图谱实体', exact: true }).fill('D2')
  await selected(page).click()
  await expect(page.getByRole('button', { name: '关系图谱', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('[data-graph-selection]')).toBeVisible()
  await graphReady(page)
  await page.screenshot({ path: test.info().outputPath('phone-graph.png') })
  await page.getByRole('button', { name: '实体目录', exact: true }).click()
  await expect(page.getByRole('searchbox', { name: '搜索图谱实体', exact: true })).toHaveValue('D2')
  await expect(selected(page)).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: '关系图谱', exact: true }).click()
  await page.keyboard.press('Control+f')
  await expect(page.getByRole('searchbox', { name: '搜索图谱实体', exact: true })).toBeFocused()
  await noOverflow(page)
  await page.screenshot({ path: test.info().outputPath('phone-directory.png') })
})

test('path discovery can select its endpoints from the full directory and return to the focused object', async ({
  page,
}) => {
  await fixture(page)
  await open(page)
  await selected(page).click()
  await page.getByRole('button', { name: '路径发现', exact: true }).click()
  await expect(page.locator('footer')).toContainText('20 节点')
  await selected(page).click()
  await directory(page)
    .locator(`[data-directory-node="${ids.get('delivery')}"]`)
    .click()
  await expect(page.getByText('路径分析完成', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '退出路径分析', exact: true }).click()
  await expect(page.getByRole('button', { name: '聚焦实体', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('[data-graph-selection]')).toContainText('系统架构设计')
})

test('node details, analysis, 3D and export controls remain reachable and follow the dark surface', async ({
  page,
}) => {
  const state = await fixture(page)
  await open(page)
  await selected(page).click()
  await page.getByRole('button', { name: '查看详情与来源', exact: true }).click()
  await expect(page.getByRole('region', { name: '图谱节点详情' })).toBeVisible()
  await graphReady(page)
  const canvasBounds = (await page.getByRole('region', { name: '知识图谱画布', exact: true }).boundingBox())!
  const detailBounds = (await page.getByRole('region', { name: '图谱节点详情', exact: true }).boundingBox())!
  expect(canvasBounds.x + canvasBounds.width).toBeLessThanOrEqual(detailBounds.x)
  await page.screenshot({ path: test.info().outputPath('entity-details.png'), animations: 'disabled' })
  await page.getByRole('button', { name: '关闭详情面板', exact: true }).click()
  await expect(page.locator('[data-graph-selection]')).toBeVisible()
  await expect(page.getByRole('button', { name: '查看详情与来源', exact: true })).toBeFocused()
  await page.getByRole('button', { name: '网络分析', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '网络分析', exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('network-analysis.png'), animations: 'disabled' })
  await expect(page.getByRole('button', { name: '拖动图谱统计栏', exact: true })).toBeHidden()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '更多画布工具', exact: true }).click()
  await page.getByRole('button', { name: '切换至 3D 空间', exact: true }).click()
  await graphReady(page)
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '导出图谱图片', exact: true }).click()
  await expect(page.getByRole('button', { name: '下载 PNG', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '工作空间与外观设置', exact: true }).click()
  await page.getByRole('button', { name: '界面外观', exact: true }).click()
  await page.getByRole('dialog', { name: '界面外观' }).getByText('深色', { exact: true }).click()
  await page.keyboard.press('Escape')
  await expect
    .poll(() =>
      page.locator('[data-graph-directory-page]').evaluate((element) => {
        const rgb = getComputedStyle(element).backgroundColor.match(/\d+/g)?.map(Number) || []
        return rgb.slice(0, 3).every((value) => value < 80)
      }),
    )
    .toBe(true)
  await noOverflow(page)
  await graphReady(page)
  await page.screenshot({ path: test.info().outputPath('dark-b.png') })
  const nextNode = facts.nodes.find((node) => node.label === '技术选型')!
  await directory(page)
    .locator(`[data-directory-node="${ids.get(nextNode.id)}"]`)
    .click()
  await graphReady(page)
  await expect(page.locator('[data-graph-renderer="3d"]')).toBeVisible()
  await expect(page.getByRole('region', { name: '当前实体摘要', exact: true })).toContainText(nextNode.label)
  await page.screenshot({ path: test.info().outputPath('3d-selected-node.png'), animations: 'disabled' })
  expect(state.writes).toEqual([])
})

test('empty graph retains a usable scope picker without showing illustrative nodes', async ({ page }) => {
  const state = await fixture(page, { empty: true })
  await page.goto('/graph', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-graph-directory-page]')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('heading', { name: '选择或导入知识图谱', exact: true })).toBeVisible()
  await expect(directory(page)).toHaveCount(0)
  await expect(page.getByRole('group', { name: '图谱画布工具', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '网络分析', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '选择图谱', exact: true }).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('scope-picker.png'), animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath('empty-b.png') })
  expect(state.writes).toEqual([])
})

test('type filters update the directory and the current graph counts, then clear back to the loaded scope', async ({
  page,
}) => {
  const state = await fixture(page)
  await open(page)
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

test('a graph read error keeps retry available and does not appear as an empty graph', async ({ page }) => {
  const state = await fixture(page)
  state.failRead = true
  const failedRead = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/api/v1/kg/graph' && response.status() === 503,
  )
  await page.goto('/graph', { waitUntil: 'domcontentloaded' })
  await failedRead
  const notice = page.getByRole('alert').filter({ hasText: '图谱读取暂时不可用' })
  await expect(notice).toBeVisible()
  await expect(directory(page).getByText('当前范围暂无节点', { exact: true })).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath('error-b.png'), animations: 'disabled' })
  state.failRead = false
  await notice.getByRole('button', { name: '重新读取', exact: true }).click()
  await expect(notice).toHaveCount(0)
  await expect(selected(page)).toBeVisible()
  await graphReady(page)
  expect(state.writes).toEqual([])
})

test('phone graph filters and scope retain readable inputs and viewport-safe controls', async ({ page }) => {
  await fixture(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await open(page)
  await selected(page).click()
  await page.getByRole('button', { name: /^筛选/ }).click()
  const filters = page.getByRole('dialog', { name: '图谱筛选', exact: true })
  await expect(filters).toBeVisible()
  const typeSearch = filters.getByRole('textbox', { name: '搜索实体类型', exact: true })
  expect(
    await typeSearch.evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize)),
  ).toBeGreaterThanOrEqual(16)
  await noOverflow(page)
  await page.screenshot({ path: test.info().outputPath('phone-filters.png'), animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(filters).toHaveCount(0)
  await page.getByRole('button', { name: '选择图谱', exact: true }).first().click()
  const scope = page.getByRole('dialog', { name: '选择图谱范围', exact: true })
  await expect(scope).toBeVisible()
  const search = scope.getByRole('searchbox')
  expect(
    await search.evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize)),
  ).toBeGreaterThanOrEqual(16)
  await expect(scope.getByRole('button', { name: '清空范围', exact: true })).toBeInViewport()
  await noOverflow(page)
  await page.screenshot({ path: test.info().outputPath('phone-scope-picker.png'), animations: 'disabled' })
})
