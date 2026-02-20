import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Knowledge import menu', () => {
  it('includes the expected import/config actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-import-menu.tsx'), 'utf8')

    expect(src).toContain('上传文件')
    expect(src).toContain('通过 URL')
    expect(src).toContain('URL 批量（Connector）')
    expect(src).toContain('Website Crawl')
    expect(src).toContain('管线配置')
  })
})

