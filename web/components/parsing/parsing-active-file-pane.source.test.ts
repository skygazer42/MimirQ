import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('parsing active file pane source', () => {
  it('keys the PDF viewer by active file, active run, and reset token so reopening a parsed PDF remounts a fresh preview instance', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'), 'utf8')

    expect(src).toContain('pdfPreviewResetToken: number')
    expect(src).toContain("const pdfViewerKey = `${activeFile.id}:${activeFile.activeRunId || activeRun?.id || 'default'}:${pdfPreviewResetToken}`")
    expect(src).toContain('key={pdfViewerKey}')
  })

  it('uses a dense parsed stats strip and a quieter toc wrapper', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'), 'utf8')

    expect(src).toContain('const parsedStatItems =')
    expect(src).not.toContain('StatsGrid')
    expect(src).not.toContain('StatCard')
    expect(src).toContain('border-b border-border/60 bg-background/80 px-5 py-2.5')
    expect(src).toContain('overflow-y-auto overscroll-contain no-scrollbar pl-2')
    expect(src).toContain("dragScroll={rightPanelMode === 'markdown'}")
    expect(src).toContain('scrollContainerSelector=".parsing-md-scroll"')
  })

  it('treats the governance action footer like a floating control dock instead of a flat strip', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'), 'utf8')

    expect(src).toContain('border-t border-border/75 bg-background/94 px-6 py-4')
    expect(src).toContain('shadow-[0_-10px_24px_-18px_rgba(15,23,42,0.22)]')
    expect(src).toContain('text-[11px] leading-5 text-muted-foreground/72')
  })

  it('surfaces normalized element summaries for seals and equations in the stats rail', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'), 'utf8')

    expect(src).toContain('const activeElementSummaryItems = useMemo(')
    expect(src).toContain('const activeElementHighlightItems = useMemo(')
    expect(src).toContain("label: '印章'")
    expect(src).toContain("label: '公式'")
    expect(src).toContain("label: '主印章'")
    expect(src).toContain("label: '公式样例'")
    expect(src).toContain('结构元素')
  })

  it('mounts the extraction panel for parsed documents so structured field extraction stays in the workbench flow', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'), 'utf8')

    expect(src).toContain("from '@/components/parsing/parsing-extract-panel'")
    expect(src).toContain("from '@/components/parsing/parsing-elements-panel'")
    expect(src).toContain('<ParsingExtractPanel')
    expect(src).toContain('<ParsingElementsPanel')
    expect(src).toContain('documentId={activeFile.libraryId || null}')
    expect(src).toContain('const selectedExtractElement = useMemo(')
    expect(src).toContain('const selectedExtractOverlayId = useMemo(')
    expect(src).toContain('const pdfBoxesByPage = useMemo(')
    expect(src).toContain('const pdfActiveBlockIds = useMemo(')
    expect(src).toContain('证据定位')
  })
})
