import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion monitor page-client layout', () => {
  it('keeps dashboard charts separate from the task toolbar and uses a denser operations header', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).not.toContain('toolbar={')
    expect(src).toContain('任务明细')
    expect(src).toContain('placeholder="搜索任务 ID 或文件名"')
    expect(src).toContain('运行正常')
    expect(src).not.toContain('SYSTEM_STATUS')
    expect(src).toContain('最近窗口内未发现错误任务')
    expect(src).toContain('size="full"')
    expect(src).toContain('topClassName="px-3 md:px-4 xl:px-5 pb-3"')
    expect(src).toContain('bodyClassName="px-3 md:px-4 xl:px-5 pb-10 z-10"')
    expect(src).toContain('图表与错误画像直接铺在主画布上，避免额外外层卡片')
  })
})
