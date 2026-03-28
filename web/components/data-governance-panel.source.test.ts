import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('data governance panel source', () => {
  it('uses explicit spans and semantic buttons instead of fake button roles or inline render IIFEs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'data-governance-panel.tsx'), 'utf8')

    expect(src).not.toContain('role="button"')
    expect(src).not.toContain('{(() => {')
    expect(src).toContain('<span className="h-1.5 w-1.5 rounded-full bg-primary/20" aria-hidden="true" />')
    expect(src).toContain('<span>智能文档清洗、标注与结构化处理中枢</span>')
    expect(src).toContain('<span className="w-1.5 h-1.5 rounded-full bg-sky-500/10 dark:bg-sky-500/20" aria-hidden="true" />')
    expect(src).toContain('<span>智能文档结构化处理与质量修复</span>')
    expect(src).toContain('aria-label="关闭提示"')
    expect(src).toContain('aria-label="打开文件上传对话框"')
    expect(src).toContain('aria-label={`打开文件：${file.filename}`}')
    expect(src).toContain('aria-label="收起右侧面板"')
    expect(src).toContain('const contentBody =')
  })
})
