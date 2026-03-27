import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingPage workbench scaffold', () => {
  it('moves the scaffold rendering into the extracted shell component', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    const shellSrc = fs.readFileSync(path.resolve(__dirname, 'parsing-workbench-shell.tsx'), 'utf8')

    expect(fs.existsSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-library-browser.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-library-preview-pane.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-page-utils.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-sidebar-pane.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-mobile-queue-content.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-mobile-inspector-content.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-workbench-shell.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-types.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'use-parsing-editor-actions.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'use-parsing-library-actions.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'use-parsing-page-state.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'use-parsing-queue-actions.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'use-parsing-run-actions.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'use-parsing-view-state.ts'))).toBe(true)
    expect(src).toContain('ParsingWorkbenchShell')
    expect(src).not.toContain('WorkbenchScaffold')
    expect(src).not.toContain('ParsingActiveFilePane')
    expect(src).not.toContain('ParsingLibraryBrowser')
    expect(src).not.toContain('ParsingLibraryPreviewPane')
    expect(src).not.toContain('ParsingSidebarPane')

    expect(shellSrc).toContain('WorkbenchScaffold')
    expect(shellSrc).toContain('ParsingActiveFilePane')
    expect(shellSrc).toContain('ParsingLibraryBrowser')
    expect(shellSrc).toContain('ParsingLibraryPreviewPane')
    expect(shellSrc).toContain('ParsingSidebarPane')
    expect(shellSrc).toContain('ParsingMobileQueueContent')
    expect(shellSrc).toContain('ParsingMobileInspectorContent')
  })

  it('moves page-local state and lifecycle wiring into the dedicated hook', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    const hookSrc = fs.readFileSync(path.resolve(__dirname, 'use-parsing-page-state.ts'), 'utf8')

    expect(src).toContain('useParsingPageState')
    expect(src).not.toContain("const [queueOpen, setQueueOpen] = useState(false)")
    expect(src).not.toContain('const cancelParse = useCallback(')
    expect(src).not.toContain("globalThis.window.localStorage.getItem('mimirq_parsing_image_caption_enabled')")

    expect(hookSrc).toContain('export function useParsingPageState(')
    expect(hookSrc).toContain("const [queueOpen, setQueueOpen] = useState(false)")
    expect(hookSrc).toContain('const cancelParse = useCallback(')
    expect(hookSrc).toContain("globalThis.window.localStorage.getItem('mimirq_parsing_image_caption_enabled')")
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

  it('moves editor and governance callbacks into the dedicated hook', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    const hookSrc = fs.readFileSync(path.resolve(__dirname, 'use-parsing-editor-actions.ts'), 'utf8')

    expect(src).toContain('useParsingEditorActions')
    expect(src).not.toContain('const copyMarkdown = async () =>')
    expect(src).not.toContain('const handleSaveEdit = async () =>')
    expect(src).not.toContain('const handleSubmitToGovernance = () =>')

    expect(hookSrc).toContain('export function useParsingEditorActions(')
    expect(hookSrc).toContain('const copyMarkdown = useCallback(')
    expect(hookSrc).toContain('const handleSaveEdit = useCallback(')
    expect(hookSrc).toContain('const handleSubmitToGovernance = useCallback(')
  })

  it('moves queue deletion and drag-drop callbacks into the dedicated hook', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    const hookSrc = fs.readFileSync(path.resolve(__dirname, 'use-parsing-queue-actions.ts'), 'utf8')

    expect(src).toContain('useParsingQueueActions')
    expect(src).not.toContain('const removeFile = (fileId: string) =>')
    expect(src).not.toContain('const moveFileToFolder = useCallback(')
    expect(src).not.toContain('const handleFolderDrop = useCallback(')

    expect(hookSrc).toContain('export function useParsingQueueActions(')
    expect(hookSrc).toContain('const removeFile = useCallback(')
    expect(hookSrc).toContain('const moveFileToFolder = useCallback(')
    expect(hookSrc).toContain('const handleFolderDrop = useCallback(')
  })

  it('moves library sync and derived view state into the dedicated hook', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    const hookSrc = fs.readFileSync(path.resolve(__dirname, 'use-parsing-view-state.ts'), 'utf8')

    expect(src).toContain('useParsingViewState')
    expect(src).not.toContain('const librarySyncQuery = useQuery(')
    expect(src).not.toContain('const activeRun = useMemo(')
    expect(src).not.toContain('const visibleQueueFiles = useMemo(')
    expect(src).not.toContain('const activeLibraryFile = useMemo(')

    expect(hookSrc).toContain('export function useParsingViewState(')
    expect(hookSrc).toContain("from '@tanstack/react-query'")
    expect(hookSrc).toContain('const librarySyncQuery = useQuery(')
    expect(hookSrc).toContain('const activeLibraryContentQuery = useQuery(')
    expect(hookSrc).not.toContain('const syncLibraryFromServer = useCallback(')
    expect(hookSrc).toContain('const activeRun = useMemo(')
    expect(hookSrc).toContain('const visibleQueueFiles = useMemo(')
    expect(hookSrc).toContain('const activeLibraryFile = useMemo(')
  })
})
