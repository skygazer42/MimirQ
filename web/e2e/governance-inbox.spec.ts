import path from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

const evidence = process.env.GOVERNANCE_EVIDENCE_DIR || path.resolve(__dirname, '../../artifacts/rebrand/governance-inbox-v1')
const duplicate = '开始作业前必须确认设备已经停止运行，并核对维护计划与现场记录。'
const original = ['# 设备维护手册', '', '## 03 日常检查与维护', '', '本章说明设备的日常维护要求、检查记录和异常处理流程。作业人员应先核对设备状态，再按维护周期完成检查。', '', duplicate, duplicate, '', '| 检查项目 | 检查要求 | 周期 |', '| --- | --- | --- |', '| 运行状态 | 检查振动、噪声和指示灯 | 每日 |', '| 润滑系统 | 核对油位，检查管路和密封 | 每周 |', '| 安全装置 | 确认限位、急停和保护装置 | 每月 |', '', '## 维护记录', '', '完成检查后，在台账中记录设备编号、作业时间、检查结果与后续安排。发现异常时，应先暂停作业，确认安全后再进行处理。', '', '联系邮箱 maintenance@example.test，值班电话 13800000000。', '', ...Array.from({ length: 5 }, (_, index) => '记录 ' + (index + 1) + '：完成维护后记录设备状态与维护人员签字，并复核相关资料。')].join('\n')
async function json(route: Route, body: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }) }
async function fixture(page: Page) {
  await page.setViewportSize({ width: 1600, height: 1000 })
  const documents = Array.from({ length: 12 }, (_, index) => ({ id: 'gov-' + (index + 1), filename: index === 0 ? '设备维护手册.pdf' : index === 1 ? '安全操作规范.docx' : '产品资料与维护记录-' + (index + 1) + '.md', file_type: index === 0 ? 'pdf' : index === 1 ? 'docx' : 'md', file_size: index === 0 ? 2516582 : 86120, status: 'completed', created_at: '2026-10-22T02:00:00Z', updated_at: '2026-10-22T02:00:00Z', error_message: null }))
  const state = { documents, failClean: false, filteredClean: false, failScan: false, failContent: false, holdScan: null as Promise<void> | null, holdClean: null as Promise<void> | null, scanStarted: 0 }
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: documents })
  await page.addInitScript(() => {
    document.addEventListener('DOMContentLoaded', () => {
      const style = document.createElement('style')
      style.textContent = 'nextjs-portal { display: none !important; }'
      document.head.appendChild(style)
    }, { once: true })
    if (!localStorage.getItem('theme')) localStorage.setItem('theme', 'light')
    localStorage.setItem('mimirq.surfaceTheme', 'ocean')
    localStorage.setItem('mimirq.themeColor', '#20262e')
    const put = IDBObjectStore.prototype.put
    IDBObjectStore.prototype.put = function (...args: Parameters<typeof put>) {
      if ((window as unknown as { failGovernanceSave?: boolean }).failGovernanceSave && this.name === 'doc_contents') throw new DOMException('测试：缓存空间不足', 'QuotaExceededError')
      return put.apply(this, args)
    }
  })
  await page.route('**/api/v1/parsing/documents**', async route => {
    const url = new URL(route.request().url())
    if (/\/content$/.test(url.pathname)) {
      if (state.failContent) return json(route, { detail: '正文服务暂不可用' }, 503)
      const id = url.pathname.split('/documents/')[1]?.split('/')[0]
      const markdown = id === 'gov-1' ? original : '# 安全操作规范\n\n核对作业范围，确认工具与设备处于安全状态。'
      return json(route, { document_id: id, parser_backend: 'text', markdown_content: markdown, original_markdown_content: markdown })
    }
    if (route.request().method() === 'GET' && /\/documents\/?$/.test(url.pathname)) return json(route, { items: state.documents, total: state.documents.length })
    return route.fallback()
  })
  await page.route('**/api/v1/pipeline/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/governance-analyze')) {
      state.scanStarted++
      if (state.holdScan) await state.holdScan
      if (state.failScan) return json(route, { detail: '检测服务暂不可用' }, 503)
      return json(route, { issues: [{ code: 'pii_email', severity: 'warning', message: '检测到邮箱信息', count: 1 }, { code: 'pii_phone', severity: 'warning', message: '检测到电话信息', count: 1 }], suggested_pipeline_patch: {} })
    }
    if (url.pathname.endsWith('/clean-preview')) {
      if (state.holdClean) await state.holdClean
      if (state.failClean) return json(route, { detail: '清洗服务暂不可用' }, 503)
      if (state.filteredClean) return json(route, { markdown: '', issues: [], dropped: true, drop_reason: '正文内容不足', diff_unified: '', rule_stats: [] })
      const body = route.request().postDataJSON()
      return json(route, { markdown: body.markdown.replace(duplicate + '\n' + duplicate, duplicate).replace('maintenance@example.test', '[邮箱已脱敏]').replace('13800000000', '[电话已脱敏]'), issues: [], dropped: false, diff_unified: '- maintenance@example.test\n+ [邮箱已脱敏]', rule_stats: [] })
    }
    return route.fallback()
  })
  return state
}
async function openInbox(page: Page) {
  await page.goto('/data-governance', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '数据治理', exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.locator('[data-governance-file]')).toHaveCount(12)
  await expect(page.locator('[data-governance-document]')).toContainText('设备维护手册')
  await page.evaluate(() => document.fonts.ready)
}
async function noOverflow(page: Page) { expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1) }

test('governance checks, cleans, retains failed saves and reloads saved content and tags', async ({ page }) => {
  const state = await fixture(page)
  await openInbox(page)
  const reader = page.locator('[data-governance-reader]')
  const panes = await Promise.all([
    page.locator('[data-governance-queue]').boundingBox(),
    page.getByRole('region', { name: '文档正文', exact: true }).boundingBox(),
    page.getByRole('complementary', { name: '治理工具箱', exact: true }).boundingBox(),
  ])
  expect(panes.every(Boolean)).toBe(true)
  const [directory, documentPane, toolbox] = panes as NonNullable<typeof panes[number]>[]
  expect(directory.x + directory.width).toBeLessThan(documentPane.x)
  expect(documentPane.x + documentPane.width).toBeLessThan(toolbox.x)
  expect(Math.abs(documentPane.y - toolbox.y)).toBeLessThanOrEqual(1)
  await page.getByRole('button', { name: '收起治理工具', exact: true }).click()
  await expect(page.getByRole('tab', { name: '质量检测', exact: true })).toBeHidden()
  expect((await page.getByRole('region', { name: '文档正文', exact: true }).boundingBox())!.width).toBeGreaterThan(documentPane.width)
  await page.getByRole('button', { name: '展开治理工具', exact: true }).click()
  await expect(reader).toContainText('尚未检测')
  state.failScan = true
  await page.getByRole('button', { name: '开始检测', exact: true }).click()
  await expect(reader.getByRole('alert')).toContainText('完整检测未完成')
  await expect(reader).toContainText('尚未检测')
  await page.screenshot({ path: path.join(evidence, 'scan-error.png') })
  state.failScan = false
  await page.getByRole('button', { name: '重试检测', exact: true }).click()
  await expect(page.getByRole('button', { name: '重新检测', exact: true })).toBeVisible()
  await expect(page.locator('[aria-label="检测问题"] button')).toHaveCount(3)
  await page.screenshot({ path: path.join(evidence, 'desktop.png') })
  await page.locator('[aria-label="检测问题"] button').first().click()
  await page.screenshot({ path: path.join(evidence, 'issue-detail.png') })
  await page.getByRole('button', { name: '定位到正文', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '编辑文档正文' })).toHaveValue(original)
  expect(await page.getByRole('textbox', { name: '编辑文档正文' }).evaluate((element: HTMLTextAreaElement) => element.value.slice(element.selectionStart, element.selectionEnd))).toBe(duplicate)
  await page.getByRole('button', { name: '预览', exact: true }).click()
  await page.getByRole('tab', { name: '智能清洗' }).click()
  state.failClean = true
  await page.getByRole('button', { name: '运行清洗', exact: true }).click()
  await expect(reader.getByRole('alert')).toBeVisible()
  await expect(page.locator('[data-governance-document]')).toContainText('maintenance@example.test')
  await page.screenshot({ path: path.join(evidence, 'clean-error.png') })
  state.failClean = false
  state.filteredClean = true
  await page.getByRole('button', { name: '运行清洗', exact: true }).click()
  await expect(reader.getByRole('alert')).toBeVisible()
  await expect(page.locator('[data-governance-document]')).toContainText('maintenance@example.test')
  state.filteredClean = false
  await page.getByRole('button', { name: '运行清洗', exact: true }).click()
  await expect(page.locator('[data-governance-document]')).toContainText('[邮箱已脱敏]')
  await page.getByRole('tab', { name: '分类归档' }).click()
  await page.getByLabel('文档分类', { exact: true }).selectOption({ label: '技术文档' })
  await page.getByLabel('文档标签', { exact: true }).fill('维护记录')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await page.evaluate(() => { (window as unknown as { failGovernanceSave: boolean }).failGovernanceSave = true })
  await page.getByRole('button', { name: '保存并继续切块', exact: true }).click()
  await expect(reader.getByRole('alert')).toContainText('保存失败')
  await expect(page).toHaveURL(/data-governance$/)
  await expect(reader).toContainText('维护记录')
  await page.screenshot({ path: path.join(evidence, 'save-error.png') })
  await page.evaluate(() => { (window as unknown as { failGovernanceSave: boolean }).failGovernanceSave = false })
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(reader).toContainText('治理结果已保存')
  await page.reload()
  await expect(page.locator('[data-governance-document]')).toContainText('[邮箱已脱敏]')
  await expect(reader).toContainText('治理结果已保存')
  await page.getByRole('tab', { name: '分类归档' }).click()
  await expect(page.getByLabel('文档分类', { exact: true })).toHaveValue('技术文档')
  await expect(page.getByRole('button', { name: '删除标签 维护记录' })).toBeVisible()
  await page.locator('[data-governance-file="gov-2"]').click()
  await expect(page.locator('[data-governance-document]')).toContainText('安全操作规范')
  await page.locator('[data-governance-file="gov-1"]').click()
  await expect(page.locator('[data-governance-document]')).toContainText('[邮箱已脱敏]')
  await noOverflow(page)
  await page.getByRole('button', { name: '保存并继续切块', exact: true }).click()
  await expect(page).toHaveURL(/\/chunk-preview/, { timeout: 60_000 })
})

test('governance binds delayed operations to the initiating document and preserves other drafts', async ({ page }) => {
  const state = await fixture(page)
  await openInbox(page)
  let finishScan!: () => void
  state.holdScan = new Promise(resolve => { finishScan = resolve })
  await page.getByRole('button', { name: '开始检测', exact: true }).click()
  await expect.poll(() => state.scanStarted).toBe(1)
  await page.locator('[data-governance-file="gov-2"]').click()
  finishScan()
  await expect(page.locator('[data-governance-reader]')).toContainText('尚未检测')
  await page.locator('[data-governance-file="gov-1"]').click()
  await expect(page.getByRole('button', { name: '重新检测', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  await page.getByRole('textbox', { name: '编辑文档正文' }).fill(original + '\n\n文档一的草稿。')
  await page.locator('[data-governance-file="gov-2"]').click()
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  await page.getByRole('textbox', { name: '编辑文档正文' }).fill('# 安全操作规范\n\n文档二的草稿。')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('[data-governance-reader]')).toContainText('治理结果已保存')
  await page.locator('[data-governance-file="gov-1"]').click()
  await expect(page.locator('[data-governance-document]')).toContainText('文档一的草稿。')
  await expect(page.locator('[data-governance-reader]')).toContainText('修改尚未保存')
  let finishClean!: () => void
  state.holdClean = new Promise(resolve => { finishClean = resolve })
  await page.getByRole('tab', { name: '智能清洗' }).click()
  await page.getByRole('button', { name: '运行清洗', exact: true }).click()
  await expect(page.getByRole('button', { name: '正在清洗…' })).toBeVisible()
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  await page.getByRole('textbox', { name: '编辑文档正文' }).fill('# 后来的人工编辑\n\n不要被旧请求覆盖。')
  finishClean()
  await expect(page.getByRole('textbox', { name: '编辑文档正文' })).toHaveValue('# 后来的人工编辑\n\n不要被旧请求覆盖。')
})

test('governance supports phone navigation, themes, search, configuration and content retry', async ({ page }) => {
  const state = await fixture(page)
  await openInbox(page)
  await page.getByRole('button', { name: '治理配置', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('清洗规则')
  await page.screenshot({ path: path.join(evidence, 'configuration.png') })
  await page.keyboard.press('Escape')
  await page.getByRole('searchbox', { name: '搜索治理文档' }).fill('不存在')
  await expect(page.locator('[data-governance-file]')).toHaveCount(0)
  await page.screenshot({ path: path.join(evidence, 'no-matches.png') })
  await page.getByRole('button', { name: '清除文档搜索' }).click()
  await page.setViewportSize({ width: 1280, height: 800 })
  await noOverflow(page)
  await page.screenshot({ path: path.join(evidence, 'laptop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '收起侧边栏', exact: true }).click()
  await expect.poll(async () => page.locator('#mimirq-sidebar').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
  await expect(page.locator('[data-governance-queue]')).toBeVisible()
  await expect(page.locator('[data-governance-reader]')).toBeHidden()
  await page.screenshot({ path: path.join(evidence, 'phone-queue.png') })
  await page.locator('[data-governance-file="gov-1"]').click()
  await expect(page.locator('[data-governance-reader]')).toBeVisible()
  await page.screenshot({ path: path.join(evidence, 'phone-reader.png') })
  await noOverflow(page)
  await page.getByRole('button', { name: '返回文档队列' }).click()
  await expect(page.locator('[data-governance-file="gov-1"]')).toBeFocused()
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.evaluate(() => { localStorage.setItem('theme', 'dark') })
  await page.reload()
  await expect(page.locator('[data-governance-document]')).toContainText('设备维护手册')
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.screenshot({ path: path.join(evidence, 'dark.png') })
  await noOverflow(page)
  state.failContent = true
  await page.locator('[data-governance-file="gov-2"]').click()
  await expect(page.getByRole('heading', { name: '正文加载失败' })).toBeVisible()
  await page.screenshot({ path: path.join(evidence, 'content-error.png') })
  state.failContent = false
  await page.getByRole('button', { name: '重新加载正文' }).click()
  await expect(page.locator('[data-governance-document]')).toContainText('安全操作规范')
})

test('annotation results separate document attributes, keywords and long text while retaining saved values', async ({ page }) => {
  await fixture(page)
  const longTags = [
    '本章说明设备的日常维护要求、检查记录和异常处理流程。作业人员应先核对设备状态，再按维护周期完成检查。',
    '完成检查后，在台账中记录设备编号、作业时间、检查结果与后续安排。发现异常时，应先暂停作业，确认安全后再进行处理。',
  ]
  const keywords = ['维护计划', '作业人员', '设备状态', '安全装置', '润滑系统', '检查结果', '维护记录']
  const annotationTexts = ['设备维护手册', ...keywords, longTags[1]]
  await page.route('**/api/v1/pipeline/auto-annotations', route => json(route, {
    annotations: annotationTexts.map((text, index) => ({ text, type: index === 0 ? 'entity' : 'keyword', label: index === 0 ? '实体' : '关键词', start: original.indexOf(text), end: original.indexOf(text) + text.length })),
    document_tags: [
      { type: 'topic', value: '设备维护' }, { type: 'industry', value: '工业制造' },
      { type: 'doc_type', value: '操作手册' }, { type: 'sensitivity', value: 'internal' },
      ...[...keywords, ...longTags].map(value => ({ type: 'keyword', value })),
    ].map(tag => ({ ...tag, label: tag.type, confidence: .85, source: 'rules' })),
    summary: null, text_chars: original.length, scanned_chars: original.length, truncated: false,
    strategy: 'rules', providers_used: ['cpu'], warnings: [],
  }))
  await openInbox(page)
  await page.getByRole('tab', { name: '数据标注', exact: true }).click()
  await page.screenshot({ path: path.join(evidence, 'annotation-empty.png') })
  await page.getByRole('button', { name: '自动标注', exact: true }).click()
  const results = page.getByRole('region', { name: '文档标签', exact: true })
  const longDetails = page.locator('details').filter({ has: page.getByText('长文本标签', { exact: true }) })
  await expect(results.getByText('内部', { exact: true })).toBeVisible()
  await expect(results.getByRole('list', { name: '关键词', exact: true }).getByRole('listitem')).toHaveCount(7)
  await expect(longDetails.getByText(longTags[1], { exact: true })).toBeHidden()
  await expect(page.getByText('9 条标注', { exact: true })).toBeVisible()
  await page.screenshot({ path: path.join(evidence, 'annotation-populated.png') })
  await longDetails.locator('summary').click()
  await expect(longDetails.getByText(longTags[1], { exact: true })).toBeVisible()
  await noOverflow(page)
  await page.screenshot({ path: path.join(evidence, 'annotation-long-text.png') })
  await longDetails.locator('summary').press('Enter')
  await expect(longDetails.getByText(longTags[1], { exact: true })).toBeHidden()
  await page.getByRole('button', { name: '界面外观', exact: true }).click()
  await page.getByRole('radio', { name: '米白配色', exact: true }).press('Space')
  await expect(page.locator('html')).toHaveAttribute('data-surface-theme', 'earth')
  await page.keyboard.press('Escape')
  await page.screenshot({ path: path.join(evidence, 'annotation-earth.png') })
  const records = page.locator('details').filter({ has: page.locator('ul[aria-label="正文标注"]') })
  await records.locator('summary').click()
  await expect(records.getByRole('listitem')).toHaveCount(9)
  await page.getByRole('button', { name: '删除标注 设备维护手册', exact: true }).click()
  await expect(records.getByRole('listitem')).toHaveCount(8)
  await page.screenshot({ path: path.join(evidence, 'annotation-records.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '收起侧边栏', exact: true }).click()
  await expect.poll(async () => page.locator('#mimirq-sidebar').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
  await page.locator('[data-governance-file="gov-1"]').click()
  await longDetails.locator('summary').click()
  await noOverflow(page)
  await expect(longDetails.getByText(longTags[1], { exact: true })).toBeVisible()
  await page.screenshot({ path: path.join(evidence, 'annotation-phone.png') })
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('[data-governance-reader]')).toContainText('治理结果已保存')
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.evaluate(() => localStorage.setItem('theme', 'dark'))
  await page.reload()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.getByRole('tab', { name: '数据标注', exact: true }).click()
  await expect(page.getByText('8 条标注', { exact: true })).toBeVisible()
  await records.locator('summary').click()
  await expect(records.getByRole('listitem')).toHaveCount(8)
  await expect(records.getByRole('button', { name: '删除标注 设备维护手册', exact: true })).toHaveCount(0)
  await expect(records.getByText(longTags[1], { exact: true })).toBeVisible()
  await page.screenshot({ path: path.join(evidence, 'annotation-dark.png') })
  await page.getByRole('tab', { name: '分类归档', exact: true }).click()
  await expect(page.getByRole('button', { name: '删除标签 internal', exact: true })).toBeVisible()
  await page.getByText('长文本标签', { exact: true }).click()
  await expect(page.getByRole('button', { name: '删除标签 ' + longTags[1], exact: true })).toBeVisible()
  await page.getByRole('tab', { name: '数据标注', exact: true }).click()
  await page.getByRole('button', { name: '自动标注', exact: true }).click()
  await expect(results.getByText('内部', { exact: true })).toBeVisible()
  await noOverflow(page)
  await page.screenshot({ path: path.join(evidence, 'annotation-dark-populated.png') })
})

test('classification uses tag values, separates long text and retains manual edits through failures and reload', async ({ page }) => {
  await fixture(page)
  const longTags = [
    '设备检修前应逐项核对断电、挂牌、保护装置和人员到位情况，确认现场安全后再开始操作。',
    '完成检查后，在台账中记录设备编号、作业时间、检查结果与后续安排。发现异常时，应先暂停作业，确认安全后再进行处理。',
  ]
  const documentTags = [
    { type: 'category', label: '分类', value: '维护指南' },
    { type: 'domain', label: '领域', value: '企业知识库' },
    { type: 'industry', label: '行业', value: '工业制造' },
    { type: 'sensitivity', label: '敏感度', value: 'internal' },
    ...['维护计划', '作业人员', '设备状态', '安全装置', '润滑系统', '检查结果', '维护记录', '异常处理', '日常检查', '安全操作'].map(value => ({ type: 'keyword', label: '语义关键词', value })),
    ...longTags.map(value => ({ type: 'quality', label: '质量线索', value })),
  ]
  let failClassification = true
  await page.route('**/api/v1/pipeline/auto-annotations', route => failClassification
    ? json(route, { detail: '分类服务暂时不可用' }, 503)
    : json(route, {
      annotations: [], document_tags: documentTags.map(tag => ({ ...tag, confidence: .85, source: 'cpu' })),
      summary: null, text_chars: original.length, scanned_chars: original.length, truncated: false,
      strategy: 'rules', providers_used: ['cpu'], warnings: [],
    }))
  await openInbox(page)
  await page.getByRole('tab', { name: '分类归档', exact: true }).click()
  await page.screenshot({ path: path.join(evidence, 'classifier-empty.png') })
  await page.getByLabel('文档分类', { exact: true }).selectOption({ label: '技术文档' })
  await page.getByLabel('文档标签', { exact: true }).fill('现场复核')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  await page.getByRole('button', { name: '自动分类', exact: true }).click()
  await expect(page.getByText('自动分类失败，请重试', { exact: true })).toBeVisible()
  await expect(page.getByLabel('文档分类', { exact: true })).toHaveValue('技术文档')
  await expect(page.getByRole('button', { name: '删除标签 现场复核', exact: true })).toBeVisible()
  failClassification = false
  await page.getByRole('button', { name: '自动分类', exact: true }).click()
  await expect(page.getByLabel('文档分类', { exact: true })).toHaveValue('维护指南')
  await expect(page.getByText('17 个标签', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '删除标签 现场复核', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '删除标签 领域', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '删除标签 分类', exact: true })).toHaveCount(0)
  await expect(page.getByRole('list', { name: '已添加标签', exact: true })).toContainText('内部')
  await expect(page.getByRole('button', { name: '删除标签 ' + longTags[1], exact: true })).toBeHidden()
  await page.screenshot({ path: path.join(evidence, 'classifier-populated.png') })
  const longDetails = page.locator('details').filter({ has: page.locator('ul[aria-label="长文本标签"]') })
  await longDetails.locator('summary').click()
  await expect(longDetails.getByRole('listitem')).toHaveCount(2)
  await expect(longDetails.getByText(longTags[1], { exact: true })).toBeVisible()
  await page.screenshot({ path: path.join(evidence, 'classifier-long-text.png') })
  await page.getByRole('button', { name: '删除标签 ' + longTags[0], exact: true }).click()
  await expect(longDetails.getByRole('listitem')).toHaveCount(1)
  await longDetails.locator('summary').press('Enter')
  const suggestions = page.locator('details').filter({ has: page.locator('ul[aria-label="推荐标签"]') })
  await suggestions.locator('summary').click()
  await expect(suggestions.getByRole('button', { name: '添加推荐标签 内部', exact: true })).toHaveCount(0)
  await suggestions.getByRole('button', { name: '添加推荐标签 指南', exact: true }).click()
  await expect(suggestions.getByRole('button', { name: '添加推荐标签 指南', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '删除标签 指南', exact: true })).toBeVisible()
  await suggestions.locator('summary').click()
  await page.evaluate(() => { (window as unknown as { failGovernanceSave: boolean }).failGovernanceSave = true })
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('[data-governance-reader]').getByRole('alert')).toContainText('保存失败')
  await expect(page.getByLabel('文档分类', { exact: true })).toHaveValue('维护指南')
  await page.evaluate(() => { (window as unknown as { failGovernanceSave: boolean }).failGovernanceSave = false })
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('[data-governance-reader]')).toContainText('治理结果已保存')
  await page.reload()
  await page.getByRole('tab', { name: '分类归档', exact: true }).click()
  await expect(page.getByLabel('文档分类', { exact: true })).toHaveValue('维护指南')
  await expect(page.getByRole('button', { name: '删除标签 internal', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '删除标签 现场复核', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '删除标签 指南', exact: true })).toBeVisible()
  await longDetails.locator('summary').click()
  await expect(longDetails.getByRole('listitem')).toHaveCount(1)
  await expect(longDetails.getByText(longTags[1], { exact: true })).toBeVisible()
  await longDetails.locator('summary').click()
  await page.getByRole('button', { name: '界面外观', exact: true }).click()
  await page.getByRole('radio', { name: '米白配色', exact: true }).press('Space')
  await expect(page.locator('html')).toHaveAttribute('data-surface-theme', 'earth')
  await page.keyboard.press('Escape')
  await page.screenshot({ path: path.join(evidence, 'classifier-earth.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '收起侧边栏', exact: true }).click()
  await expect.poll(async () => page.locator('#mimirq-sidebar').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
  await page.locator('[data-governance-file="gov-1"]').click()
  await noOverflow(page)
  await page.screenshot({ path: path.join(evidence, 'classifier-phone.png') })
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.evaluate(() => localStorage.setItem('theme', 'dark'))
  await page.reload()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.getByRole('tab', { name: '分类归档', exact: true }).click()
  await expect(page.getByLabel('文档分类', { exact: true })).toHaveValue('维护指南')
  await noOverflow(page)
  await page.screenshot({ path: path.join(evidence, 'classifier-dark.png') })
})
