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
    expect(src).toContain('border-b border-border/60 bg-[linear-gradient(180deg,hsl(var(--background)/0.96),hsl(var(--muted)/0.35))] px-5 py-3')
    expect(src).toContain('rounded-full border border-border/60 bg-card/88 px-2.5 py-1')
    expect(src).toContain('max-h-[min(72vh,calc(100vh-13rem))] overflow-y-auto overscroll-contain custom-scrollbar')
    expect(src).not.toContain('max-h-[calc(100%-2rem)] overflow-y-auto overscroll-contain no-scrollbar pl-2')
    expect(src).toContain("dragScroll={rightPanelMode === 'markdown'}")
    expect(src).toContain('scrollContainerSelector=".parsing-md-scroll"')
  })


  it('keeps the markdown table-of-contents out of medium-width live smoke layouts', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'), 'utf8')

    expect(src).toContain('self-start 2xl:sticky 2xl:top-0 2xl:block')
    expect(src).not.toContain('self-start xl:sticky xl:top-0 xl:block')
  })

  it('keeps the PDF source preview from collapsing into a narrow sliver beside markdown preview', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'), 'utf8')

    expect(src).toContain('xl:flex-row')
    expect(src).toContain('xl:flex-[1.42]')
    expect(src).toContain("isPdf ? 'w-full min-w-0 xl:flex-[0.92]' : 'w-full min-w-0'")
    expect(src).not.toContain('lg:flex-row')
    expect(src).not.toContain('lg:flex-[1.42]')
    expect(src).not.toContain('lg:flex-[0.92]')
  })

  it('labels the parsed PDF navigation as positioning blocks rather than an abstract layout mode', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'), 'utf8')

    expect(src).toContain('定位块')
    expect(src).toContain('解析定位块')
    expect(src).toContain('点击左侧 PDF 框选可跳到这里')
    expect(src).toContain('const activeImageElements = useMemo(')
    expect(src).toContain('const reviewEntries = useMemo<ReviewEntry[]>')
    expect(src).toContain('function getElementImageSrc(')
    expect(src).toContain("{reviewEntries.map((reviewEntry, index) => {")
    expect(src).toContain("if (reviewEntry.type === 'image')")
    expect(src).toContain('<AuthImage')
    expect(src).toContain('共 {activeImageElements.length} 张图片')
    expect(src).not.toContain('仅预览前 12 张')
  })

  it('treats the governance action footer like a floating control dock instead of a flat strip', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'), 'utf8')

    expect(src).toContain('border-t border-border/60 bg-card px-6 py-4')
    expect(src).toContain('shadow-[0_-10px_24px_-18px_rgba(15,23,42,0.22)]')
    expect(src).toContain('text-[11px] leading-5 text-muted-foreground/78')
  })

  it('surfaces normalized element summaries for seals and equations in the stats rail', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'), 'utf8')

    expect(src).toContain('const activeElementSummaryItems = useMemo(')
    expect(src).toContain('const activeElementHighlightItems = useMemo(')
    expect(src).toContain("label: '印章'")
    expect(src).toContain("label: '公式'")
    expect(src).toContain("label: '主印章'")
    expect(src).toContain("label: '公式样例'")
    expect(src).toContain("label: '图片子类'")
    expect(src).toContain('结构元素')
  })

  it('mounts the extraction panel for parsed documents so structured field extraction stays in the workbench flow', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'), 'utf8')

    expect(src).toContain("from '@/components/parsing/parsing-extract-panel'")
    expect(src).toContain("from '@/components/parsing/parsing-elements-panel'")
    expect(src).toContain('<ParsingExtractPanel')
    expect(src).toContain('<ParsingElementsPanel')
    expect(src).toContain('documentId={activeFile.libraryId || null}')
    expect(src).toContain('pages: element.pages ?? null')
    expect(src).toContain('const selectedExtractElement = useMemo(')
    expect(src).toContain('const selectedExtractOverlayId = useMemo(')
    expect(src).toContain('const pdfBoxesByPage = useMemo(')
    expect(src).toContain('const pdfActiveBlockIds = useMemo(')
    expect(src).toContain('Array.isArray(evidence?.pages)')
    expect(src).toContain('selectedExtractEvidence.evidence.visual_kind')
    expect(src).toContain('跨页')
    expect(src).toContain('证据定位')
  })

  it('keeps the PDF page overlay and layout review list bidirectionally synchronized', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'), 'utf8')

    expect(src).toContain('const layoutReviewCardRefs = useRef<Map<string, HTMLButtonElement>>(new Map())')
    expect(src).toContain("onRightPanelModeChange('blocks')")
    expect(src).toContain('layoutReviewCardRefs.current.get(activeBlockId)')
    expect(src).toContain('scrollIntoView({')
    expect(src).toContain("block: 'nearest'")
    expect(src).toContain('data-layout-entry-id={entry.id}')
  })
})
