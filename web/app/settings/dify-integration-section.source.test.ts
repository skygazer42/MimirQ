import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('settings Dify integration section', () => {
  it('builds Dify external knowledge bindings from real datasets', () => {
    const section = read('./_sections/dify-integration-section.tsx')
    const hook = read('./use-settings-page-state.ts')
    const page = read('./page.tsx')

    expect(section).toContain("datasetApi, type SystemSettings")
    expect(section).toContain('datasetApi.list({ limit: 200 })')
    expect(section).toContain('Dify 外部知识库')
    expect(section).toContain('knowledge_id')
    expect(section).toContain('复制接入地址')
    expect(section).toContain('生成绑定')
    expect(section).toContain('当前绑定')
    expect(section).toContain('已选择数据集')
    expect(section).not.toContain('<textarea')

    expect(hook).toContain('DEFAULT_DIFY_EXTERNAL_KNOWLEDGE')
    expect(hook).toContain('difyExternalKnowledgeMerged')
    expect(hook).toContain('updateDifyExternalKnowledge')

    expect(page).toContain("import { DifyIntegrationSection } from './_sections/dify-integration-section'")
    expect(page).toContain("{ id: 'sec-dify', label: 'Dify 接入'")
    expect(page.indexOf("{ id: 'sec-rag', label: 'RAG 配置'")).toBeLessThan(
      page.indexOf("{ id: 'sec-dify', label: 'Dify 接入'")
    )
    expect(page.indexOf("{ id: 'sec-dify', label: 'Dify 接入'")).toBeLessThan(
      page.indexOf("{ id: 'sec-url', label: 'URL 采集'")
    )
  })
})
