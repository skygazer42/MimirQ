import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingPage workbench scaffold', () => {
  it('uses WorkbenchScaffold for the outer layout', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-library-browser.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-library-preview-pane.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-sidebar-pane.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-mobile-queue-content.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-mobile-inspector-content.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-types.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'use-parsing-library-actions.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'use-parsing-run-actions.ts'))).toBe(true)
    expect(src).toContain('WorkbenchScaffold')
    expect(src).toContain('ParsingActiveFilePane')
    expect(src).toContain('ParsingLibraryBrowser')
    expect(src).toContain('ParsingLibraryPreviewPane')
    expect(src).toContain('ParsingSidebarPane')
  })

  it('moves library browser rendering details into the extracted component', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    const browserSrc = fs.readFileSync(path.resolve(__dirname, 'parsing-library-browser.tsx'), 'utf8')

    expect(src).not.toContain('const isLibraryEmpty =')
    expect(src).not.toContain('<FileQueueItem')
    expect(src).not.toContain('<div key={f.id} draggable')

    expect(browserSrc).toContain('const isLibraryEmpty =')
    expect(browserSrc).toContain('<FileQueueItem')
    expect(browserSrc).toContain('draggable')
  })

  it('moves upload and library restore callbacks into the dedicated hook', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    const hookSrc = fs.readFileSync(path.resolve(__dirname, 'use-parsing-library-actions.ts'), 'utf8')

    expect(src).toContain('useParsingLibraryActions')
    expect(src).not.toContain('const addFiles = useCallback(')
    expect(src).not.toContain('const mountLibraryFileToQueue = useCallback(')

    expect(hookSrc).toContain('export function useParsingLibraryActions(')
    expect(hookSrc).toContain('const addFiles = useCallback(')
    expect(hookSrc).toContain('const mountLibraryFileToQueue = useCallback(')
  })

  it('moves parsing run callbacks into the dedicated hook', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    const hookSrc = fs.readFileSync(path.resolve(__dirname, 'use-parsing-run-actions.ts'), 'utf8')

    expect(src).toContain('useParsingRunActions')
    expect(src).not.toContain('const parseFile = useCallback(')
    expect(src).not.toContain('const parseAllPending = async () =>')
    expect(src).not.toContain('const handleSelectRun = (runId: string) =>')

    expect(hookSrc).toContain('export function useParsingRunActions(')
    expect(hookSrc).toContain('const parseFile = useCallback(')
    expect(hookSrc).toContain('const parseAllPending = useCallback(')
    expect(hookSrc).toContain('const handleSelectRun = useCallback(')
  })
})
