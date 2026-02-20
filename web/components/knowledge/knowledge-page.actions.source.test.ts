import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage actions', () => {
  it('delegates import actions to KnowledgeWorkbenchActions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain('KnowledgeWorkbenchActions')
    expect(src).toContain('onConnectorRunCreated={handleConnectorRunCreated}')
    expect(src).not.toContain('URL_INGEST_ENABLED')
    expect(src).not.toContain('入库管线配置')
    expect(src).not.toContain('URL 批量导入（Connector）')
    expect(src).not.toContain('Website Crawl (Connector)')
  })
})
