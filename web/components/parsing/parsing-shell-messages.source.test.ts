import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('parsing and reports shell message wiring', () => {
  it('moves the owned shell copy behind next-intl lookups', () => {
    const reportsSrc = fs.readFileSync(path.resolve(__dirname, '../../app/reports/page.tsx'), 'utf8')
    const shellSrc = fs.readFileSync(path.resolve(__dirname, 'parsing-workbench-shell.tsx'), 'utf8')
    const sidebarSrc = fs.readFileSync(path.resolve(__dirname, 'parsing-sidebar-pane.tsx'), 'utf8')
    const previewSrc = fs.readFileSync(path.resolve(__dirname, 'parsing-library-preview-pane.tsx'), 'utf8')

    expect(reportsSrc).toContain("useTranslations('Reports')")
    expect(shellSrc).toContain("useTranslations('ParsingWorkbench')")
    expect(sidebarSrc).toContain("useTranslations('ParsingWorkbench')")
    expect(previewSrc).toContain("useTranslations('ParsingWorkbench')")

    expect(reportsSrc).not.toContain('正在加载报告中心...')
    expect(shellSrc).not.toContain('文档解析工作台')
    expect(shellSrc).not.toContain('选择文件开始')
    expect(sidebarSrc).not.toContain('默认解析方式')
    expect(previewSrc).not.toContain('暂无可展示的解析内容')
  })
})
