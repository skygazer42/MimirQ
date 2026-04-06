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
})
