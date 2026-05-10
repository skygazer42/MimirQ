import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage actions', () => {
  it('renders KnowledgeWorkbenchActions inside the toolbar row only for documents so retrieval and settings stay focused on their own workflows', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('KnowledgeWorkbenchActions')
    expect(src).toContain("{activeTab === 'documents' && (")
    expect(src).toContain('className="h-8 rounded-xl border border-info/20 bg-info/[0.08] px-4 text-[10px] font-medium text-info dark:text-info shadow-soft"')
    expect(src).toContain('onConnectorRunCreated={(run) => { setShowTaskCenter(true); setPeekingDocId(null); setActiveTab(\'documents\'); }}')
    expect(src).toContain('toolbar={')
    expect(src).not.toContain('URL_INGEST_ENABLED')
    expect(src).not.toContain('入库管线配置')
    expect(src).not.toContain('URL 批量导入（Connector）')
    expect(src).not.toContain('Website Crawl (Connector)')
    expect(src).not.toContain('已收藏当前配置')
    expect(src).not.toContain('收藏此配置')
  })
})
