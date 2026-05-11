import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('ParsingPage workbench scaffold', () => {
  it('moves the scaffold rendering into the extracted shell component', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'parsing-page.tsx'),
      'utf8'
    )
    const shellSrc = fs.readFileSync(
      path.resolve(__dirname, 'parsing-workbench-shell.tsx'),
      'utf8'
    )

    expect(
      fs.existsSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'))
    ).toBe(true)
    expect(
      fs.existsSync(path.resolve(__dirname, 'parsing-library-browser.tsx'))
    ).toBe(true)
    expect(
      fs.existsSync(path.resolve(__dirname, 'parsing-library-preview-pane.tsx'))
    ).toBe(true)
    expect(
      fs.existsSync(path.resolve(__dirname, 'parsing-page-utils.ts'))
    ).toBe(true)
    expect(
      fs.existsSync(path.resolve(__dirname, 'parsing-sidebar-pane.tsx'))
    ).toBe(true)
    expect(
      fs.existsSync(path.resolve(__dirname, 'parsing-mobile-queue-content.tsx'))
    ).toBe(true)
    expect(
      fs.existsSync(
        path.resolve(__dirname, 'parsing-mobile-inspector-content.tsx')
      )
    ).toBe(true)
    expect(
      fs.existsSync(path.resolve(__dirname, 'parsing-workbench-shell.tsx'))
    ).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-types.ts'))).toBe(
      true
    )
    expect(
      fs.existsSync(path.resolve(__dirname, 'use-parsing-editor-actions.ts'))
    ).toBe(true)
    expect(
      fs.existsSync(path.resolve(__dirname, 'use-parsing-library-actions.ts'))
    ).toBe(true)
    expect(
      fs.existsSync(path.resolve(__dirname, 'use-parsing-page-state.ts'))
    ).toBe(true)
    expect(
      fs.existsSync(path.resolve(__dirname, 'use-parsing-queue-actions.ts'))
    ).toBe(true)
    expect(
      fs.existsSync(path.resolve(__dirname, 'use-parsing-run-actions.ts'))
    ).toBe(true)
    expect(
      fs.existsSync(path.resolve(__dirname, 'use-parsing-view-state.ts'))
    ).toBe(true)
    expectSourceToContain(src, 'ParsingWorkbenchShell')
    expectSourceNotToContain(src, 'WorkbenchScaffold')
    expectSourceNotToContain(src, 'ParsingActiveFilePane')
    expectSourceNotToContain(src, 'ParsingLibraryBrowser')
    expectSourceNotToContain(src, 'ParsingLibraryPreviewPane')
    expectSourceNotToContain(src, 'ParsingSidebarPane')

    expectSourceToContain(shellSrc, 'WorkbenchScaffold')
    expectSourceToContain(shellSrc, 'ParsingActiveFilePane')
    expectSourceToContain(shellSrc, 'ParsingLibraryPreviewPane')
    expectSourceToContain(shellSrc, 'ParsingSidebarPane')
    expectSourceToContain(shellSrc, 'ParsingMobileQueueContent')
    expectSourceToContain(shellSrc, 'ParsingMobileInspectorContent')
    expectSourceToContain(shellSrc, 'IngestionWorkflowStepper')
    expectSourceToContain(shellSrc, 'ParsingWorkbenchMark')
    expectSourceToContain(shellSrc, 'header={')
    expectSourceNotToContain(shellSrc, '<PipelineRail />')
    expectSourceToContain(shellSrc, 'sidebarFileItems')
  })

  it('auto-restores parsed PDF source files when selecting a library-only entry so the preview pane shows the document immediately', () => {
    const shellSrc = fs.readFileSync(
      path.resolve(__dirname, 'parsing-workbench-shell.tsx'),
      'utf8'
    )

    expectSourceToContain(
      shellSrc,
      'restoreLibraryFileFromCache(activeLibraryFile.id, false)'
    )
    expectSourceToContain(shellSrc, "activeLibraryFile.status === 'parsed'")
    expectSourceToContain(shellSrc, 'activeLibraryMarkdownAvailable')
    expectSourceToContain(shellSrc, "filename.toLowerCase().endsWith('.pdf')")
    expectSourceToContain(
      shellSrc,
      'if (activeFile || !activeLibraryFile) return'
    )
    expectSourceToContain(
      shellSrc,
      'const bumpPdfPreviewResetToken = () => setPdfPreviewResetToken((prev) => prev + 1)'
    )
    expectSourceToContain(shellSrc, 'bumpPdfPreviewResetToken()')
  })

  it('adds a dataset scope bridge for knowledge-base documents in the parsing sidebar', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'parsing-page.tsx'),
      'utf8'
    )
    const shellSrc = fs.readFileSync(
      path.resolve(__dirname, 'parsing-workbench-shell.tsx'),
      'utf8'
    )
    const sidebarSrc = fs.readFileSync(
      path.resolve(__dirname, 'parsing-sidebar-pane.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'selectedDatasetId: pageState.selectedDatasetId')
    expectSourceToContain(
      src,
      'availableDatasets={viewState.availableDatasets}'
    )
    expectSourceToContain(src, 'onDatasetScopeChange={(datasetId) => {')
    expectSourceToContain(shellSrc, 'datasetOptions={datasetOptions}')
    expectSourceToContain(
      shellSrc,
      "readOnly: file.source === 'knowledge_base'"
    )
    expectSourceToContain(sidebarSrc, 'DATASET_ALL_VALUE')
    expectSourceToContain(
      sidebarSrc,
      'onDatasetScopeChange(value === DATASET_ALL_VALUE ? null : value)'
    )
  })

  it('moves page-local state and lifecycle wiring into the dedicated hook', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'parsing-page.tsx'),
      'utf8'
    )
    const hookSrc = fs.readFileSync(
      path.resolve(__dirname, 'use-parsing-page-state.ts'),
      'utf8'
    )

    expectSourceToContain(src, 'useParsingPageState')
    expectSourceNotToContain(
      src,
      'const [queueOpen, setQueueOpen] = useState(false)'
    )
    expectSourceNotToContain(src, 'const cancelParse = useCallback(')
    expectSourceNotToContain(
      src,
      "globalThis.window.localStorage.getItem('mimirq_parsing_image_caption_enabled')"
    )

    expectSourceToContain(hookSrc, 'export function useParsingPageState(')
    expectSourceToContain(
      hookSrc,
      'const [queueOpen, setQueueOpen] = useState(false)'
    )
    expectSourceToContain(
      hookSrc,
      'const [pdfPreviewResetToken, setPdfPreviewResetToken] = useState(0)'
    )
    expectSourceToContain(hookSrc, 'const cancelParse = useCallback(')
    expectSourceToContain(
      hookSrc,
      "globalThis.window.localStorage.getItem('mimirq_parsing_image_caption_enabled')"
    )
  })

  it('keeps the optional library browser extracted even though the desktop sidebar now uses a unified file tree', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'parsing-page.tsx'),
      'utf8'
    )
    const browserSrc = fs.readFileSync(
      path.resolve(__dirname, 'parsing-library-browser.tsx'),
      'utf8'
    )
    const shellSrc = fs.readFileSync(
      path.resolve(__dirname, 'parsing-workbench-shell.tsx'),
      'utf8'
    )

    expectSourceNotToContain(src, 'const isLibraryEmpty =')
    expectSourceNotToContain(src, '<FileQueueItem')
    expectSourceNotToContain(src, '<div key={f.id} draggable')

    expectSourceToContain(browserSrc, 'const isLibraryEmpty =')
    expectSourceToContain(browserSrc, '<FileQueueItem')
    expectSourceToContain(browserSrc, 'draggable')
    expectSourceNotToContain(shellSrc, 'ParsingLibraryBrowser')
  })

  it('moves upload and library restore callbacks into the dedicated hook', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'parsing-page.tsx'),
      'utf8'
    )
    const hookSrc = fs.readFileSync(
      path.resolve(__dirname, 'use-parsing-library-actions.ts'),
      'utf8'
    )

    expectSourceToContain(src, 'useParsingLibraryActions')
    expectSourceNotToContain(src, 'const addFiles = useCallback(')
    expectSourceNotToContain(
      src,
      'const mountLibraryFileToQueue = useCallback('
    )

    expectSourceToContain(hookSrc, 'export function useParsingLibraryActions(')
    expectSourceToContain(hookSrc, 'const addFiles = useCallback(')
    expectSourceToContain(
      hookSrc,
      'const mountLibraryFileToQueue = useCallback('
    )
  })

  it('moves parsing run callbacks into the dedicated hook', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'parsing-page.tsx'),
      'utf8'
    )
    const hookSrc = fs.readFileSync(
      path.resolve(__dirname, 'use-parsing-run-actions.ts'),
      'utf8'
    )

    expectSourceToContain(src, 'useParsingRunActions')
    expectSourceNotToContain(src, 'const parseFile = useCallback(')
    expectSourceNotToContain(src, 'const parseAllPending = async () =>')
    expectSourceNotToContain(src, 'const handleSelectRun = (runId: string) =>')

    expectSourceToContain(hookSrc, 'export function useParsingRunActions(')
    expectSourceToContain(hookSrc, 'const parseFile = useCallback(')
    expectSourceToContain(hookSrc, 'const parseAllPending = useCallback(')
    expectSourceToContain(hookSrc, 'const handleSelectRun = useCallback(')
  })

  it('moves editor and governance callbacks into the dedicated hook', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'parsing-page.tsx'),
      'utf8'
    )
    const hookSrc = fs.readFileSync(
      path.resolve(__dirname, 'use-parsing-editor-actions.ts'),
      'utf8'
    )

    expectSourceToContain(src, 'useParsingEditorActions')
    expectSourceNotToContain(src, 'const copyMarkdown = async () =>')
    expectSourceNotToContain(src, 'const handleSaveEdit = async () =>')
    expectSourceNotToContain(src, 'const handleSubmitToGovernance = () =>')

    expectSourceToContain(hookSrc, 'export function useParsingEditorActions(')
    expectSourceToContain(hookSrc, 'const copyMarkdown = useCallback(')
    expectSourceToContain(hookSrc, 'const handleSaveEdit = useCallback(')
    expectSourceToContain(
      hookSrc,
      'const handleSubmitToGovernance = useCallback('
    )
  })

  it('moves queue deletion and drag-drop callbacks into the dedicated hook', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'parsing-page.tsx'),
      'utf8'
    )
    const hookSrc = fs.readFileSync(
      path.resolve(__dirname, 'use-parsing-queue-actions.ts'),
      'utf8'
    )

    expectSourceToContain(src, 'useParsingQueueActions')
    expectSourceNotToContain(src, 'const removeFile = (fileId: string) =>')
    expectSourceNotToContain(src, 'const moveFileToFolder = useCallback(')
    expectSourceNotToContain(src, 'const handleFolderDrop = useCallback(')

    expectSourceToContain(hookSrc, 'export function useParsingQueueActions(')
    expectSourceToContain(hookSrc, 'const removeFile = useCallback(')
    expectSourceToContain(hookSrc, 'const moveFileToFolder = useCallback(')
    expectSourceToContain(hookSrc, 'const handleFolderDrop = useCallback(')
  })

  it('moves library sync and derived view state into the dedicated hook', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'parsing-page.tsx'),
      'utf8'
    )
    const hookSrc = fs.readFileSync(
      path.resolve(__dirname, 'use-parsing-view-state.ts'),
      'utf8'
    )

    expectSourceToContain(src, 'useParsingViewState')
    expectSourceNotToContain(src, 'const librarySyncQuery = useQuery(')
    expectSourceNotToContain(src, 'const activeRun = useMemo(')
    expectSourceNotToContain(src, 'const visibleQueueFiles = useMemo(')
    expectSourceNotToContain(src, 'const activeLibraryFile = useMemo(')

    expectSourceToContain(hookSrc, 'export function useParsingViewState(')
    expectSourceToContain(hookSrc, "from '@tanstack/react-query'")
    expectSourceToContain(hookSrc, 'const librarySyncQuery = useQuery(')
    expectSourceToContain(
      hookSrc,
      'const activeLibraryContentQuery = useQuery('
    )
    expectSourceNotToContain(
      hookSrc,
      'const syncLibraryFromServer = useCallback('
    )
    expectSourceToContain(hookSrc, 'const activeRun = useMemo(')
    expectSourceToContain(hookSrc, 'const visibleQueueFiles = useMemo(')
    expectSourceToContain(hookSrc, 'const activeLibraryFile = useMemo(')
  })
})
