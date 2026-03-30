import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('pdf page render worker source', () => {
  it('configures pdf.js for fake-worker rendering with OffscreenCanvas-friendly factories', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-page-render.worker.ts'), 'utf8')

    expect(src).toContain("import 'pdfjs-dist/build/pdf.worker.mjs'")
    expect(src).toContain("from 'pdfjs-dist/build/pdf.mjs'")
    expect(src).toContain('class WorkerCanvasFactory')
    expect(src).toContain('new OffscreenCanvas(width, height)')
    expect(src).toContain('class WorkerFilterFactory')
    expect(src).toContain('disableFontFace: true')
    expect(src).toContain('useSystemFonts: false')
    expect(src).toContain('CanvasFactory: WorkerCanvasFactory')
    expect(src).toContain('FilterFactory: WorkerFilterFactory')
    expect(src).toContain('expose(api)')
  })

  it('drops worker render task bookkeeping during render teardown', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-page-render.worker.ts'), 'utf8')

    expect(src).toContain('let activeRenderTask: RenderTask | null = null')
    expect(src).toContain('if (activeRenderTask && pageRenderTasks.get(pageIndex) === activeRenderTask)')
    expect(src).toContain('pageRenderTasks.delete(pageIndex)')
  })
})
