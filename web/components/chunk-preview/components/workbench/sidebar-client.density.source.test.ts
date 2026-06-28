import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunk preview sidebar density source', () => {
  it('keeps the settings rail compact and uses helper copy blocks', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'sidebar-client.tsx'), 'utf8')

    expect(src).toContain("'p-4'")
    expect(src).not.toContain("'p-6'")
    expect(src).toContain("w-[19rem] border-r border-border/60")
    expect(src).toContain('function SidebarChip(')
    expect(src).toContain('function SidebarNote(')
  })

  it('keeps the sidebar palette restrained around theme tokens', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'sidebar-client.tsx'), 'utf8')

    expect(src).toContain('const SIDEBAR_BASE_TONE')
    expect(src).toContain('const SIDEBAR_PRIMARY_TONE')
    expect(src).not.toMatch(/\b(?:border|bg|text)-(?:sky|amber|emerald|violet|cyan|purple|red|blue|orange)-\d/)
    expect(src).not.toContain('accent-emerald')
  })

  it('compresses the file queue toolbar and avoids a duplicated batch-ingest helper card', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'sidebar-client.tsx'), 'utf8')

    expect(src).toContain('const selectedIngestCount = selectedIngestFileIds.size')
    expect(src).toContain('data-chunk-file-queue')
    expect(src).toContain("t('sidebar.fileList.batchIngestIdle')")
    expect(src).toContain("t('sidebar.fileList.batchIngestSelected'")
    expect(src).toContain('mt-2 flex items-center justify-between gap-2 rounded-xl border border-border/35 bg-muted/10 px-2 py-1.5 shadow-none')
    expect(src).not.toContain("t('sidebar.fileList.batchIngestHint')")
    expect(src).not.toContain('flex items-center justify-between gap-2 rounded-xl border border-border/45 bg-background/70 px-2.5 py-2')
  })

  it('keeps chunk analysis metrics dense enough for the narrow sidebar', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'sidebar-client.tsx'), 'utf8')

    expect(src).toContain('data-chunk-stat-grid')
    expect(src).toContain('grid grid-cols-3 gap-1.5')
    expect(src).toContain('compactStatCardClass')
    expect(src).toContain('compactStatLabelClass')
    expect(src).toContain('compactStatValueClass')
    expect(src).not.toContain('<div className="grid grid-cols-2 gap-2">')
    expect(src).not.toContain("mt-1 text-[16px] font-medium leading-none")
  })
})
