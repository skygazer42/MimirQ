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
    expectSourceToContain(shellSrc, 'PipelineRail')
    expectSourceToContain(shellSrc, '<PipelineRail />')
    expectSourceToContain(shellSrc, 'ParsingInspectorPanel')
    expectSourceToContain(shellSrc, 'header={')
    expectSourceToContain(shellSrc, 'data-testid="parsing-workbench-title"')
    expectSourceToContain(shellSrc, 'data-testid="parsing-workbench-grid"')
    expectSourceToContain(shellSrc, 'pointer-events-none absolute inset-0 overflow-hidden rounded-[28px]')
    expectSourceToContain(shellSrc, 'border-dashed border-info/30')
    expectSourceToContain(shellSrc, "t('sidebar.uploadFile')")
    expectSourceToContain(shellSrc, 'scopeFileCount={currentFolderFileCount}')
    expectSourceToContain(shellSrc, 'queueFileCount={visibleQueueFiles.length}')
    expectSourceNotToContain(shellSrc, 'files={visibleQueueFiles}')
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
    expectSourceToContain(shellSrc, "activeLibraryFile?.status === 'parsed'")
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

  it('keeps the selected document inspector compact with collapsible details', () => {
    const shellSrc = fs.readFileSync(
      path.resolve(__dirname, 'parsing-workbench-shell.tsx'),
      'utf8'
    )

    expectSourceToContain(shellSrc, 'data-testid="parsing-selected-file-summary"')
    expectSourceToContain(shellSrc, '<summary className="flex cursor-pointer list-none items-start justify-between gap-3 px-4 py-4 [&::-webkit-details-marker]:hidden">')
    expectSourceToContain(shellSrc, '<span className="group-open:hidden">展开</span>')
    expectSourceToContain(shellSrc, '<span className="hidden group-open:inline">收起</span>')
    expectSourceToContain(shellSrc, 'function ParsingInspectorDisclosure')
    expectSourceToContain(shellSrc, '<ParsingInspectorDisclosure title="解析详情" icon={Info}>')
    expectSourceToContain(shellSrc, '<ParsingInspectorDisclosure title="内容概览" icon={Clock3}>')
    expectSourceToContain(
      shellSrc,
      '<ParsingInspectorDisclosure title="快捷操作" icon={Gauge} defaultOpen={isPending || isError}>'
    )
    expectSourceToContain(shellSrc, '<span className="group-open:hidden">展开</span>')
    expectSourceToContain(shellSrc, '<span className="hidden group-open:inline">收起</span>')
  })

  it('keeps the static inspector out of common desktop widths so the parsing preview remains readable', () => {
    const shellSrc = fs.readFileSync(
      path.resolve(__dirname, 'parsing-workbench-shell.tsx'),
      'utf8'
    )

    expectSourceToContain(shellSrc, 'motion-reduce:transition-none 2xl:flex')
    expectSourceNotToContain(shellSrc, 'motion-reduce:transition-none xl:flex')
  })

  it('keeps the governance submit action visually semantic even when disabled', () => {
    const shellSrc = fs.readFileSync(
      path.resolve(__dirname, 'parsing-workbench-shell.tsx'),
      'utf8'
    )

    expectSourceToContain(
      shellSrc,
      'const canSubmitToGovernance = Boolean(activeFile && canUseMarkdownActions)'
    )
    expectSourceToContain(
      shellSrc,
      'bg-[linear-gradient(90deg,hsl(var(--info)),hsl(var(--primary)))]'
    )
    expectSourceToContain(shellSrc, 'border-info/20 bg-info/[0.10] text-info/70')
    expectSourceToContain(shellSrc, 'disabled:opacity-100')
    expectSourceToContain(shellSrc, 'disabled={!canSubmitToGovernance}')
  })

  it('adds a saved-document batch handoff queue for governance submission', () => {
    const pageSrc = fs.readFileSync(
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
    const folderTreeSrc = fs.readFileSync(
      path.resolve(__dirname, '../document-library/folder-tree.tsx'),
      'utf8'
    )
    const itemSrc = fs.readFileSync(
      path.resolve(__dirname, '../ui/file-queue-item.tsx'),
      'utf8'
    )

    expectSourceToContain(pageSrc, 'const [selectedGovernanceFileIds, setSelectedGovernanceFileIds] = useState<Set<string>>')
    expectSourceToContain(pageSrc, 'const toggleGovernanceFileSelection = useCallback(')
    expectSourceToContain(pageSrc, 'selectedGovernanceFileIds={selectedGovernanceFileIds}')
    expectSourceToContain(pageSrc, 'onToggleGovernanceFileSelection={toggleGovernanceFileSelection}')
    expectSourceToContain(pageSrc, 'onSubmitSelectedToGovernance={editorActions.handleSubmitSelectedToGovernance}')
    expectSourceToContain(shellSrc, "file.governanceStatus === 'ready'")
    expectSourceToContain(shellSrc, '提交选中文档')
    expectSourceToContain(shellSrc, '待提交')
    expectSourceToContain(sidebarSrc, 'onToggleFileSelected={onToggleGovernanceFileSelection}')
    expectSourceToContain(folderTreeSrc, 'onToggleFileSelected?.(file.id)')
    expectSourceToContain(folderTreeSrc, 'aria-label={file.isSelected ? \'取消选择待提交文档\' : \'选择待提交文档\'}')
    expectSourceToContain(itemSrc, "governanceStatus?: 'draft' | 'ready' | 'submitted'")
  })

  it('renders parsing status metrics as semantic cards instead of a flat table grid', () => {
    const shellSrc = fs.readFileSync(
      path.resolve(__dirname, 'parsing-workbench-shell.tsx'),
      'utf8'
    )

    expectSourceToContain(shellSrc, 'function ParsingStatusMetricGrid')
    expectSourceToContain(shellSrc, 'const PARSING_STATUS_METRIC_TONES')
    expectSourceToContain(shellSrc, 'grid grid-cols-2 gap-2')
    expectSourceToContain(shellSrc, 'border-success/25 bg-success/[0.07]')
    expectSourceToContain(shellSrc, 'border-info/25 bg-info/[0.07]')
    expectSourceToContain(shellSrc, 'border-warning/25 bg-warning/[0.08]')
    expectSourceToContain(shellSrc, '<ParsingStatusMetricGrid')
    expectSourceToContain(shellSrc, "{ label: '已解析', value: parsedCount, tone: 'success' }")
    expectSourceToContain(shellSrc, "{ label: '解析中', value: parsingCount, tone: 'info' }")
    expectSourceToContain(shellSrc, "{ label: '待处理', value: pendingCount, tone: 'warning' }")
    expectSourceToContain(shellSrc, "{ label: '队列', value: queueFileCount, tone: 'muted' }")
  })

  it('renders the desktop inspector as a static right rail matching the parsing design', () => {
    const shellSrc = fs.readFileSync(
      path.resolve(__dirname, 'parsing-workbench-shell.tsx'),
      'utf8'
    )

    expectSourceToContain(
      shellSrc,
      "const PARSING_INSPECTOR_WIDTH_KEY = 'mimirq.parsing.inspectorWidth'"
    )
    expectSourceToContain(shellSrc, 'const DEFAULT_PARSING_INSPECTOR_WIDTH = 410')
    expectSourceToContain(shellSrc, 'const MIN_PARSING_INSPECTOR_WIDTH = 320')
    expectSourceToContain(shellSrc, 'const MAX_PARSING_INSPECTOR_WIDTH = 560')
    expectSourceToContain(shellSrc, 'const COLLAPSED_PARSING_INSPECTOR_HOTZONE_WIDTH = 36')
    expectSourceToContain(shellSrc, 'data-testid="parsing-static-inspector"')
    expectSourceToContain(shellSrc, 'const [inspectorCollapsed, setInspectorCollapsed] = useState(false)')
    expectSourceToContain(
      shellSrc,
      'style={{ width: inspectorCollapsed ? COLLAPSED_PARSING_INSPECTOR_HOTZONE_WIDTH : inspectorWidth }}'
    )
    expectSourceToContain(shellSrc, "aria-label={inspectorCollapsed ? '展开解析信息侧栏' : '收起解析信息侧栏'}")
    expectSourceToContain(shellSrc, "title={inspectorCollapsed ? '展开解析信息侧栏' : '收起解析信息侧栏'}")
    expectSourceToContain(shellSrc, 'onClick={() => setInspectorCollapsed((collapsed) => !collapsed)}')
    expectSourceToContain(shellSrc, "inspectorCollapsed ? 'left-0' : 'left-[-0.875rem]'")
    expectSourceToContain(shellSrc, 'transition-[left,opacity,background-color,color,box-shadow]')
    expectSourceToContain(shellSrc, 'opacity-0 hover:opacity-100 focus-visible:opacity-100')
    expectSourceToContain(shellSrc, "{inspectorCollapsed ? <PanelRightOpen")
    expectSourceToContain(shellSrc, 'aria-label="调整解析信息宽度"')
    expectSourceToContain(shellSrc, 'onPointerDown={handleResizePointerDown}')
    expectSourceToContain(shellSrc, 'role="slider"')
    expectSourceToContain(shellSrc, 'cursor-col-resize')
    expectSourceToContain(shellSrc, 'inspectorCollapsed ? null : (')
    expectSourceToContain(shellSrc, '<ParsingInspectorPanel')
    expectSourceToContain(shellSrc, '<ResizableParsingInspectorRail>')
    expectSourceNotToContain(shellSrc, 'function ParsingInspectorDock')
    expectSourceNotToContain(shellSrc, 'data-testid="parsing-inspector-dock"')
    expectSourceNotToContain(shellSrc, 'rightPanel={')
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
    expectSourceToContain(
      hookSrc,
      "globalThis.window.localStorage.getItem('mimirq_parsing_image_ocr_enabled')"
    )
    expectSourceToContain(
      hookSrc,
      "globalThis.window.localStorage.getItem('mimirq_parsing_vlm_correction_enabled')"
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
