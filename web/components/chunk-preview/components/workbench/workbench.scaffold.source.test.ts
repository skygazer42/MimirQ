import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Chunk preview workbench scaffold', () => {
  it('adopts WorkbenchScaffold layout conventions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'index.tsx'), 'utf8')

    expect(src).toContain('WorkbenchScaffold')
    expect(src).toContain('function ChunkPreviewWorkbenchHeader')
    expect(src).toContain('header={<ChunkPreviewWorkbenchHeader />}')
    expect(src).toContain("t('workbench.header.eyebrow')")
  })

  it('does not duplicate active file facts in the page header', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'index.tsx'), 'utf8')

    expect(src).not.toContain('function ChunkPreviewHeaderStat')
    expect(src).not.toContain('function ChunkPreviewHeaderChip')
    expect(src).not.toContain("label={t('workbench.header.scope')}")
    expect(src).not.toContain("label={t('workbench.header.files')}")
    expect(src).not.toContain("label={t('workbench.header.duration')}")
    expect(src).not.toContain("label={t('workbench.header.source')}")
  })

  it('uses a single integrated empty intake canvas when no file is selected', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'index.tsx'), 'utf8')

    expect(src).toContain('function ChunkPreviewEmptyCanvas()')
    expect(src).toContain('data-chunk-preview-empty-canvas="true"')
    expect(src).toContain('currentFile && currentFileItem ? (')
    expect(src).toContain('<ChunkPreviewEmptyCanvas />')
    expect(src).not.toContain('{showOriginalPanel ? <OriginalPreview /> : null}\n              <ChunkList />')
  })

  it('keeps the empty upload surface compact and top-aligned', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'index.tsx'), 'utf8')

    expect(src).toContain('data-chunk-empty-intake-panel')
    expect(src).toContain('items-start')
    expect(src).toContain('min-h-[9rem]')
    expect(src).not.toContain('justify-center px-8 py-12')
    expect(src).not.toContain('text-4xl font-black')
    expect(src).not.toContain('md:text-5xl')
    expect(src).not.toContain('min-h-[20rem]')
  })

  it('fills the lower empty canvas with a chunking flow visual', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'index.tsx'), 'utf8')

    expect(src).toContain('data-chunk-empty-visual-map')
    expect(src).toContain("t('emptyState.visual.title')")
    expect(src).toContain("t('emptyState.visual.steps.parse')")
    expect(src).toContain('lg:grid-cols-[minmax(0,0.82fr)_minmax(24rem,1fr)]')
  })
})
