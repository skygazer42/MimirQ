import path from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'
import type { CleanPreviewRequest, GovernanceProfileOut, GovernanceProfilePayload } from '../types'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

const evidence = path.resolve(__dirname, '../../artifacts/rebrand/governance-profiles-directory-v1/tests')
const sourceEvidence = path.resolve(__dirname, '../../artifacts/rebrand/governance-profiles-source-v1/tests')
const customId = '7248dc7c-5763-4c61-a7dc-0c6279a63388'
const scripts = [{ name: '审阅清洗脚本', language: 'python' as const, stage: 'post_governance' as const, content: 'def clean(text):\n    return text' }]
const payload: GovernanceProfilePayload = { version: '1', input_formats: ['markdown'], pipeline_patch: { governance_enabled: true, governance_remove_toc_lines: true, governance_remove_noise_lines: true, governance_unwrap_lines: true, governance_remove_common_lines: true, governance_normalize_tables: true, governance_max_blank_lines: 1 }, regex_rules: [] }
const builtins: GovernanceProfileOut[] = [
  { key: 'builtin:pdf_text', name: 'PDF 文本版（修复断行/页眉页脚/表格）', description: '适用于可复制文本的 PDF：合并软换行、去重页眉页脚、表格规范化。', is_system: true, payload },
  { key: 'builtin:html_web', name: '网页 HTML（去样板/去导航）', description: '提取网页正文，清理导航与页脚。', is_system: true, payload: { ...payload, input_formats: ['html'], pipeline_patch: { governance_enabled: true, governance_remove_boilerplate: true, governance_remove_noise_lines: false, governance_html_xpath: '//main', governance_remove_images: 'decorative', governance_rule_packs: ['web_navigation', 'web_cookie_banners'] } } },
]
async function json(route: Route, body: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }) }

async function fixture(page: Page) {
  await page.setViewportSize({ width: 1600, height: 1000 })
  await installCommonApiMocks(page, { uploaded: false })
  await page.addInitScript(() => {
    if (!localStorage.getItem('theme')) localStorage.setItem('theme', 'light')
    if (!localStorage.getItem('mimirq.surfaceTheme')) localStorage.setItem('mimirq.surfaceTheme', 'ocean')
    localStorage.setItem('mimirq.themeColor', '#20262e')
    document.addEventListener('DOMContentLoaded', () => { const style = document.createElement('style'); style.textContent = 'nextjs-portal { display: none !important; }'; document.head.appendChild(style) }, { once: true })
  })
  const state = {
    profiles: [...structuredClone(builtins), { id: customId, key: 'team:inherited', name: '团队清洗配置', description: '继承 PDF 文本规则，关闭噪声清理。', is_system: false, payload: { version: '1', extends: 'builtin:pdf_text', input_formats: ['markdown'], pipeline_patch: { governance_remove_noise_lines: false }, regex_rules: [], processing_scripts: scripts } } as GovernanceProfileOut],
    failList: false, failResolved: false, failPreview: false, failSave: false, failDelete: false,
    previewStarted: 0, holdPreview: null as Promise<void> | null,
    requests: [] as Array<{ method: string; ref: string; body: unknown }>,
    previewRequests: [] as CleanPreviewRequest[], importBody: '',
  }
  await page.route('**/api/v1/pipeline/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname.endsWith('/clean-preview')) {
      state.previewStarted++
      const body = request.postDataJSON() as CleanPreviewRequest
      state.previewRequests.push(body)
      if (state.holdPreview) await state.holdPreview
      if (state.failPreview) return json(route, { detail: '清洗服务暂不可用' }, 503)
      return json(route, { markdown: body.markdown.replace('重复页眉\n', ''), changed: true, issues: [], dropped: false, rule_stats: [] })
    }
    const suffix = url.pathname.split('/governance-profiles')[1]
    if (suffix === undefined) return route.fallback()
    const ref = decodeURIComponent(suffix.split('/')[1] || '')
    const method = request.method()
    if (ref === 'import') { state.importBody = request.postData() || ''; return json(route, { created: 1, updated: 0, skipped: 0, items: [] }) }
    if (!ref && method === 'GET') {
      if (state.failList) return json(route, { detail: '目录服务暂不可用' }, 503)
      const q = url.searchParams.get('q') || ''
      const items = state.profiles.filter(item => `${item.name} ${item.key} ${item.description}`.includes(q)).map(({ payload: _, ...item }) => item)
      return json(route, { total: items.length, items })
    }
    if (!ref && method === 'POST') {
      const body = request.postDataJSON()
      state.requests.push({ method, ref, body })
      if (state.failSave) return json(route, { detail: '保存服务暂不可用' }, 503)
      const created = { ...body, id: 'a54e88f1-af26-4343-9ed5-4c6ca6b1fe98', key: body.key || 'team:copy', is_system: false }
      state.profiles.push(created)
      return json(route, created)
    }
    const index = state.profiles.findIndex(item => (item.id || item.key) === ref)
    const profile = state.profiles[index]
    if (!profile) return json(route, { detail: '配置不存在' }, 404)
    if (suffix.endsWith('/export') || suffix.endsWith('/export-ingestion-policy')) {
      state.requests.push({ method, ref, body: null }); return json(route, profile)
    }
    if (suffix.endsWith('/resolved')) {
      if (state.failResolved) return json(route, { detail: '规则服务暂不可用' }, 503)
      const parent = state.profiles.find(item => item.key === profile.payload.extends)
      return json(route, { profile, chain: parent ? [parent, profile] : [profile], effective: parent ? { ...profile.payload, pipeline_patch: { ...parent.payload.pipeline_patch, ...profile.payload.pipeline_patch } } : profile.payload })
    }
    if (method === 'PATCH') {
      const body = request.postDataJSON()
      state.requests.push({ method, ref, body })
      if (state.failSave) return json(route, { detail: '保存服务暂不可用' }, 503)
      state.profiles[index] = { ...profile, ...body }
      return json(route, state.profiles[index])
    }
    if (method === 'DELETE') {
      state.requests.push({ method, ref, body: null })
      if (state.failDelete) return json(route, { detail: '删除服务暂不可用' }, 503)
      state.profiles.splice(index, 1)
      return json(route, {})
    }
    return json(route, profile)
  })
  return state
}
async function openProfiles(page: Page) {
  await page.goto('/data-governance/profiles', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '治理配置', exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.locator('[data-profile-detail] table')).toBeVisible()
  await expect(page.locator('[data-profile-page]')).toHaveCSS('display', 'flex')
  await page.evaluate(() => document.fonts.ready)
}
async function noOverflow(page: Page) { expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1) }

test('directory selection displays actual resolved rules and previews preserve failed input and reject stale responses', async ({ page }) => {
  const state = await fixture(page)
  await openProfiles(page)
  const detail = page.locator('[data-profile-detail]')
  await expect(page.locator('[data-profile-ref="builtin:pdf_text"]')).toHaveAttribute('aria-current', 'true')
  await expect(detail.getByRole('heading', { name: 'PDF 文本版', exact: true })).toBeVisible()
  await expect(detail.getByRole('button', { name: '编辑配置', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: /自定义配置/ }).click()
  await expect(detail).toContainText('继承自 PDF 文本版')
  await expect(detail.getByRole('row', { name: /清理噪声行/ })).toContainText('关闭')
  await expect(detail.getByRole('row', { name: /移除目录行/ })).toContainText('启用')
  const input = page.getByRole('textbox', { name: '清洗前', exact: true })
  await input.fill('重复页眉\n保留这段正文。')
  const refetched = page.waitForResponse(response => response.url().includes(`${customId}/resolved`))
  await page.getByRole('button', { name: '重新加载目录', exact: true }).click()
  await refetched
  await expect(input).toHaveValue('重复页眉\n保留这段正文。')
  state.failPreview = true
  await page.getByRole('button', { name: '运行预览', exact: true }).click()
  await expect(page.locator('[data-sonner-toast]').filter({ hasText: '清洗服务暂不可用' })).toBeVisible()
  await expect(input).toHaveValue('重复页眉\n保留这段正文。')
  state.failPreview = false
  await page.getByRole('button', { name: '运行预览', exact: true }).click()
  await expect(page.locator('[data-profile-preview-output]')).toContainText('保留这段正文。')
  expect(state.previewRequests.at(-1)).toMatchObject({ remove_toc_lines: true, remove_noise_lines: false })
  let release!: () => void
  state.holdPreview = new Promise(resolve => { release = resolve })
  await page.getByRole('button', { name: '运行预览', exact: true }).click()
  await expect.poll(() => state.previewStarted).toBe(3)
  await input.fill('另一段正文。')
  release()
  await expect(page.locator('[data-profile-preview-output]')).toContainText('运行预览后')
  await expect(page.locator('[data-profile-preview-output]')).not.toContainText('保留这段正文。')
  await page.screenshot({ path: path.join(evidence, 'custom-preview.png') })
})

test('copy and edit preserve inheritance and scripts, failed drafts survive and save reads back after reload', async ({ page }) => {
  const state = await fixture(page)
  await openProfiles(page)
  await page.getByRole('button', { name: /自定义配置/ }).click()
  await page.getByRole('button', { name: '编辑配置', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByLabel('模板名称', { exact: true })).toHaveValue('团队清洗配置')
  await dialog.getByLabel('模板名称', { exact: true }).fill('团队新名称')
  state.failSave = true
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByText('保存服务暂不可用', { exact: false })).toBeVisible()
  await expect(dialog.getByLabel('模板名称', { exact: true })).toHaveValue('团队新名称')
  state.failSave = false
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(page.locator('[data-profile-detail] h2')).toHaveText('团队新名称')
  expect(state.requests.find(item => item.method === 'PATCH')).toMatchObject({ ref: customId, body: { payload: { extends: 'builtin:pdf_text', processing_scripts: scripts } } })
  await page.reload()
  await expect(page.getByRole('button', { name: /自定义配置/ })).toBeVisible()
  await page.getByRole('button', { name: /自定义配置/ }).click()
  await expect(page.locator('[data-profile-detail] h2')).toHaveText('团队新名称')
  await page.getByRole('button', { name: '当前配置更多操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '复制配置', exact: true }).click()
  await expect(dialog.getByLabel('模板名称', { exact: true })).toHaveValue('团队新名称 (copy)')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(dialog).toBeHidden()
  expect(state.requests.find(item => item.method === 'POST')).toMatchObject({ body: { payload: { extends: 'builtin:pdf_text', processing_scripts: scripts } } })
  await expect(page.locator('[data-profile-detail] h2')).toHaveText('团队新名称 (copy)')
})

test('import honors overwrite, exports target the current ref and failed deletion remains retryable', async ({ page }) => {
  const state = await fixture(page)
  await openProfiles(page)
  const download = page.waitForEvent('download')
  await page.locator('[data-profile-detail]').getByRole('button', { name: '导出', exact: true }).click()
  expect((await download).suggestedFilename()).toBe('builtin_pdf_text.governance-profile.json')
  expect(state.requests.at(-1)?.ref).toBe('builtin:pdf_text')
  await page.getByRole('button', { name: '导入', exact: true }).click()
  await page.getByRole('menuitemcheckbox', { name: '覆盖同名配置', exact: true }).click()
  await page.getByLabel('导入治理配置文件', { exact: true }).setInputFiles({ name: 'profiles.json', mimeType: 'application/json', buffer: Buffer.from('{"items":[]}') })
  await expect.poll(() => state.importBody).toContain('name="overwrite"\r\n\r\ntrue')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: /自定义配置/ }).click()
  await page.getByRole('button', { name: '当前配置更多操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '删除配置', exact: true }).click()
  state.failDelete = true
  const confirm = page.getByRole('alertdialog')
  await confirm.getByRole('button', { name: '删除配置', exact: true }).click()
  await expect(page.locator('[data-sonner-toast]').filter({ hasText: '删除服务暂不可用' })).toBeVisible()
  await expect(confirm).toBeVisible()
  expect(state.requests.at(-1)).toMatchObject({ method: 'DELETE', ref: customId })
  state.failDelete = false
  await confirm.getByRole('button', { name: '删除配置', exact: true }).click()
  await expect(confirm).toBeHidden()
  await expect(page.getByText('还没有自定义配置', { exact: true })).toBeVisible()
})

test('directory supports search, retry and mobile back focus, while surfaces follow the global theme', async ({ page }) => {
  const state = await fixture(page)
  await openProfiles(page)
  await noOverflow(page)
  await page.screenshot({ path: path.join(evidence, 'desktop.png') })
  await page.getByRole('searchbox', { name: '搜索治理配置', exact: true }).fill('不存在的配置')
  await expect(page.getByText('没有找到匹配的配置', { exact: true })).toBeVisible()
  await page.getByRole('navigation', { name: '配置列表', exact: true }).getByRole('button', { name: '清除搜索', exact: true }).click()
  await page.locator('[data-profile-ref="builtin:html_web"]').click()
  await expect(page.locator('[data-profile-detail] h2')).toHaveText('网页 HTML')
  await expect(page.getByLabel('预览输入格式', { exact: true })).toHaveValue('html')
  await expect(page.locator('[data-profile-detail] table')).toContainText('移除装饰图片')
  await expect(page.locator('[data-profile-detail] table')).toContainText('网页导航菜单、网页 Cookie 横幅')
  state.failList = true
  await page.getByRole('button', { name: '重新加载目录', exact: true }).click()
  await expect(page.locator('[data-profile-directory]').getByRole('alert')).toContainText('目录服务暂不可用', { timeout: 25_000 })
  state.failList = false
  await page.getByRole('button', { name: '重试读取', exact: true }).click()
  await expect(page.locator('[data-profile-detail] table')).toBeVisible()
  const before = await page.locator('[data-profile-detail]').evaluate(element => getComputedStyle(element.parentElement!).backgroundColor)
  await page.getByRole('button', { name: '界面外观', exact: true }).click()
  await page.getByRole('radio', { name: '米白配色', exact: true }).press('Space')
  await expect(page.locator('html')).toHaveAttribute('data-surface-theme', 'earth')
  await page.keyboard.press('Escape')
  await expect.poll(() => page.locator('[data-profile-detail]').evaluate(element => getComputedStyle(element.parentElement!).backgroundColor)).not.toBe(before)
  await page.screenshot({ path: path.join(evidence, 'earth.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '收起侧边栏', exact: true }).click()
  await expect(page.locator('[data-profile-directory]')).toBeVisible()
  await page.locator('[data-profile-ref="builtin:pdf_text"]').click()
  await expect(page.locator('[data-profile-detail] h2')).toBeFocused()
  await expect(page.locator('[data-profile-directory]')).toBeHidden()
  await noOverflow(page)
  await page.screenshot({ path: path.join(evidence, 'phone-detail.png') })
  await page.getByRole('button', { name: '返回模板目录', exact: true }).click()
  await expect(page.locator('[data-profile-ref="builtin:pdf_text"]')).toBeFocused()
  await page.screenshot({ path: path.join(evidence, 'phone-directory.png') })
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.evaluate(() => localStorage.setItem('theme', 'dark'))
  await page.reload()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await expect(page.locator('[data-profile-detail] table')).toBeVisible()
  await noOverflow(page)
  await page.screenshot({ path: path.join(evidence, 'dark.png') })
})

async function documentFixture(page: Page) {
  const preview = await fixture(page)
  const documents = [
    { id: 'parsed-one', filename: '设备维护手册.pdf', file_type: 'pdf', status: 'completed' },
    { id: 'parsed-two', filename: '第二份资料.md', file_type: 'md', status: 'completed' },
    { id: 'parsed-empty', filename: '空正文.pdf', file_type: 'pdf', status: 'completed' },
  ]
  const state = { documents, failList: false, failContent: false, holdContentId: '', holdContent: null as Promise<void> | null, contentStarted: [] as string[], listSkips: [] as number[], writes: [] as string[], pageSize: 200 }
  await page.route('**/api/v1/parsing/documents**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() !== 'GET') { state.writes.push(request.method() + ' ' + url.pathname); return json(route, {}) }
    if (url.pathname.endsWith('/content')) {
      const id = url.pathname.split('/documents/')[1].split('/')[0]
      state.contentStarted.push(id)
      if (id === state.holdContentId && state.holdContent) await state.holdContent
      if (state.failContent) return json(route, { detail: '正文服务暂不可用' }, 503)
      return json(route, { document_id: id, parser_backend: 'text', markdown_content: id === 'parsed-empty' ? '' : id === 'parsed-one' ? '# 已保存的清洗稿\n\n这不是解析原文。' : '# 第二份资料\n\n第二份正文。', original_markdown_content: id === 'parsed-one' ? '重复页眉\n# 设备维护手册\n\n解析完成后的原始正文。' : '' })
    }
    if (state.failList) return json(route, { detail: '解析目录暂不可用' }, 503)
    expect(url.searchParams.get('status')).toBe('completed')
    const skip = Number(url.searchParams.get('skip') || 0)
    state.listSkips.push(skip)
    return json(route, { total: state.documents.length, items: state.documents.slice(skip, skip + state.pageSize) })
  })
  return { preview, state }
}

test('parsed sources use original content, automatically preview across templates and preserve manual text without document writes', async ({ page }) => {
  const { preview, state } = await documentFixture(page)
  await openProfiles(page)
  const input = page.getByRole('textbox', { name: '清洗前', exact: true })
  await input.fill('手动草稿应保留。')
  await page.getByRole('button', { name: '选择已解析文档', exact: true }).click()
  const picker = page.getByRole('dialog', { name: '选择已解析文档', exact: true })
  await expect(picker.getByRole('searchbox')).toBeFocused()
  await picker.getByRole('searchbox').fill('设备')
  await expect(picker.getByRole('button', { name: /^使用文档 / })).toHaveCount(1)
  await picker.getByRole('button', { name: '使用文档 设备维护手册.pdf', exact: true }).click()
  await expect(input).toHaveValue('重复页眉\n# 设备维护手册\n\n解析完成后的原始正文。')
  await expect(input).toHaveAttribute('readonly', '')
  await expect(page.locator('[data-profile-preview-output]')).toContainText('解析完成后的原始正文。')
  await expect(page.locator('[data-preview-source]')).toContainText('解析原文')
  expect(preview.previewRequests.at(-1)?.markdown).not.toContain('已保存的清洗稿')
  await page.getByRole('button', { name: /自定义配置/ }).click()
  await expect(page.getByRole('button', { name: '更换预览文档，当前 设备维护手册.pdf', exact: true })).toBeVisible()
  await expect.poll(() => preview.previewRequests.at(-1)?.remove_noise_lines).toBe(false)
  await expect(page.locator('[data-profile-preview-output]')).toContainText('解析完成后的原始正文。')
  await page.screenshot({ path: path.join(sourceEvidence, 'document-preview.png') })
  await page.getByRole('button', { name: '手动输入', exact: true }).click()
  await expect(input).toHaveValue('手动草稿应保留。')
  await expect(input).not.toHaveAttribute('readonly', '')
  await page.getByRole('button', { name: '运行预览', exact: true }).click()
  await expect(page.locator('[data-profile-preview-output]')).toContainText('手动草稿应保留。')
  expect(state.writes).toEqual([])
})

test('source list, content and cleaning failures recover in place; late source and preview responses cannot replace the new selection', async ({ page }) => {
  const { preview, state } = await documentFixture(page)
  state.failList = true
  await openProfiles(page)
  await page.getByRole('button', { name: '选择已解析文档', exact: true }).click()
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('解析目录暂不可用')
  await expect(page.getByText('还没有已解析文档', { exact: true })).toBeHidden()
  state.failList = false
  await page.getByRole('button', { name: '重试文档列表', exact: true }).click()
  state.failContent = true
  await page.getByRole('button', { name: '使用文档 设备维护手册.pdf', exact: true }).click()
  await expect(page.locator('[data-profile-detail]').getByRole('alert')).toContainText('正文服务暂不可用')
  await expect(page.getByRole('button', { name: '重新预览', exact: true })).toBeDisabled()
  state.failContent = false
  preview.failPreview = true
  await page.getByRole('button', { name: '重试读取文档', exact: true }).click()
  await expect(page.locator('[data-sonner-toast]').filter({ hasText: '清洗服务暂不可用' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '清洗前', exact: true })).toHaveValue(/原始正文/)
  preview.failPreview = false
  await page.getByRole('button', { name: '重新预览', exact: true }).click()
  await expect(page.locator('[data-profile-preview-output]')).toContainText('原始正文')
  let releasePreview!: () => void
  preview.holdPreview = new Promise(resolve => { releasePreview = resolve })
  const started = preview.previewStarted
  await page.getByRole('button', { name: '重新预览', exact: true }).click()
  await expect.poll(() => preview.previewStarted).toBe(started + 1)
  preview.holdPreview = null
  let releaseContent!: () => void
  state.holdContentId = 'parsed-two'
  state.holdContent = new Promise(resolve => { releaseContent = resolve })
  await page.getByRole('button', { name: /^更换预览文档/ }).click()
  await page.getByRole('button', { name: '使用文档 第二份资料.md', exact: true }).click()
  await expect.poll(() => state.contentStarted).toContain('parsed-two')
  await expect(page.getByRole('textbox', { name: '清洗前', exact: true })).toHaveValue('')
  await page.getByRole('button', { name: /^更换预览文档/ }).click()
  await page.getByRole('button', { name: '使用文档 空正文.pdf', exact: true }).click()
  await expect(page.getByText('此文档没有可预览的正文，请返回文档解析检查结果。', { exact: true })).toBeVisible()
  const oldResponse = page.waitForResponse(response => response.url().endsWith('/clean-preview'))
  releasePreview(); releaseContent()
  await oldResponse
  await expect(page.getByRole('textbox', { name: '清洗前', exact: true })).toHaveValue('')
  await expect(page.locator('[data-profile-preview-output]')).not.toContainText('原始正文')
  await expect(page.locator('[data-profile-preview-output]')).not.toContainText('第二份正文')
  await page.getByRole('button', { name: /^更换预览文档/ }).click()
  await page.getByRole('button', { name: '使用文档 第二份资料.md', exact: true }).click()
  await expect(page.locator('[data-profile-preview-output]')).toContainText('第二份正文')
  await expect(page.locator('[data-preview-source]')).toContainText('已保存正文')
  expect(state.writes).toEqual([])
})

test('source picker handles pagination, mobile keyboard access and parsed Markdown under an HTML template', async ({ page }) => {
  const { preview, state } = await documentFixture(page)
  state.pageSize = 1
  await openProfiles(page)
  await page.locator('[data-profile-ref="builtin:html_web"]').click()
  await page.getByRole('button', { name: '选择已解析文档', exact: true }).click()
  const picker = page.getByRole('dialog', { name: '选择已解析文档', exact: true })
  await picker.getByRole('searchbox').fill('第二份')
  await expect(picker.getByText('没有找到匹配的文档', { exact: true })).toBeVisible()
  await picker.getByRole('button', { name: '加载更多文档', exact: true }).click()
  await picker.getByRole('button', { name: '使用文档 第二份资料.md', exact: true }).press('Enter')
  await expect(page.locator('[data-profile-preview-output]')).toContainText('第二份正文')
  expect(preview.previewRequests.at(-1)).toMatchObject({ input_format: 'markdown' })
  expect(state.listSkips).toEqual([0, 1])
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '收起侧边栏', exact: true }).click()
  await page.locator('[data-profile-ref="builtin:html_web"]').click()
  await page.getByRole('button', { name: /^更换预览文档/ }).click()
  await expect(picker.getByRole('searchbox')).toBeFocused()
  await noOverflow(page)
  await page.screenshot({ path: path.join(sourceEvidence, 'phone-picker.png') })
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: /^更换预览文档/ })).toBeFocused()
  await noOverflow(page)
  await page.screenshot({ path: path.join(sourceEvidence, 'phone-preview.png') })
})
