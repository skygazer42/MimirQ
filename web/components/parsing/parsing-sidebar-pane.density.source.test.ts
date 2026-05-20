import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingSidebarPane density', () => {
  it('keeps the parsing sidebar de-boxed and uses a unified tree instead of stacked browsers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-sidebar-pane.tsx'), 'utf8')
    const leftPanelSrc = fs.readFileSync(path.resolve(__dirname, 'parsing-left-panel.tsx'), 'utf8')

    expect(leftPanelSrc).toContain("const PARSING_LEFT_PANEL_WIDTH_KEY = 'mimirq.parsing.leftPanelWidth'")
    expect(leftPanelSrc).toContain('const DEFAULT_PARSING_LEFT_PANEL_WIDTH = 344')
    expect(leftPanelSrc).toContain('const MIN_PARSING_LEFT_PANEL_WIDTH = 280')
    expect(leftPanelSrc).toContain('const MAX_PARSING_LEFT_PANEL_WIDTH = 460')
    expect(leftPanelSrc).toContain('style={collapsed ? { width: 0 } : { width: sidebarWidth }}')
    expect(leftPanelSrc).toContain('onPointerDown={handleResizePointerDown}')
    expect(leftPanelSrc).toContain('role="separator"')
    expect(leftPanelSrc).toContain('cursor-col-resize')
    expect(leftPanelSrc).toContain('transition-[opacity,background-color,color,box-shadow]')
    expect(leftPanelSrc).toContain('opacity-0 hover:opacity-100 focus-visible:opacity-100')
    expect(leftPanelSrc).not.toContain('group-hover/sidebar:opacity-100')
    expect(leftPanelSrc).not.toContain("right-[-2.25rem] opacity-100")
    expect(src).toContain('bg-background/35 px-3 py-3')
    expect(src).toContain('border-b border-border/55 bg-card/96 px-4 py-3.5')
    expect(src).toContain('border border-info/20 bg-info/[0.10] text-info')
    expect(src).toContain('const fileTypeSummary =')
    expect(src).toContain("label: '全部'")
    expect(src).toContain("label: '文档'")
    expect(src).toContain("label: '表格'")
    expect(src).toContain("label: '其他'")
    expect(src).toContain('fileItems={sidebarFileItems}')
    expect(src).toContain("t('sidebar.imageOcrTitle')")
    expect(src).toContain("t('sidebar.vlmCorrectionTitle')")
    expect(src).not.toContain('libraryFileListContent')
    expect(src).not.toContain('rounded-2xl border border-border/60 bg-card p-2')
  })
})
