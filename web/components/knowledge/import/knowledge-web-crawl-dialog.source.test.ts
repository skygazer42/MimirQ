import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeWebCrawlDialog', () => {
  it('includes website crawl controls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-web-crawl-dialog.tsx'), 'utf8')

    expect(src).toContain('Website Crawl (Connector)')
    expect(src).toContain('URL_INGEST_ENABLED')
    expect(src).toContain('Start URLs')
    expect(src).toContain('Sitemap URLs')
    expect(src).toContain('ParserDropdown')
    expect(src).toContain('ChunkStrategyDropdown')
    expect(src).toContain('PipelineOptionsPanel')
  })
})

