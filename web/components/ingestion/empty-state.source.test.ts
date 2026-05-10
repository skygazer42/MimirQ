import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion empty state source', () => {
  it('turns the truly-empty state into a report-first empty state with a three-step guide', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'empty-state.tsx'), 'utf8')

    expect(src).toContain("mode: 'truly-empty' | 'filter-empty'")
    expect(src).toContain('处理效率线框预览')
    expect(src).toContain('预检盘点入口')
    expect(src).toContain('风险热力图预留区')
    expect(src).toContain('<svg viewBox="0 0 640 220"')
    expect(src).toContain('还没有生成数据盘点结果')
    expect(src).toContain('这个页面的职责是做入库前摸底')
    expect(src).toContain('Audit First')
    expect(src).toContain('上传')
    expect(src).toContain('扫描')
    expect(src).toContain('结论')
    expect(src).not.toContain('加载虚拟数据')
    expect(src).not.toContain('/knowledge/ingestion?demo=1')
    expect(src).toContain('入库预检')
    expect(src).not.toContain('上传首个文档')
    expect(src).not.toContain('向量索引')
    expect(src).toContain('清除过滤器')
  })
})
