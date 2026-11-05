// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('next-intl', () => ({ useTranslations: () => (key: string) => key }))
vi.mock('@/components/app-frame', () => ({
  AppFrame: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}))
vi.mock('@/components/workbench', () => ({
  WorkbenchScaffold: ({ mainPanel }: { mainPanel?: React.ReactNode }) => <div>{mainPanel}</div>,
  WorkbenchPanelDialog: () => null,
}))
vi.mock('@/components/ui/knowledge-ops-hero', () => ({
  KnowledgeOpsHero: () => null,
  KnowledgeOpsFlowCard: () => null,
  KNOWLEDGE_OPS_SUMMARY_PANEL_CLASS: '',
}))
vi.mock('@/components/parsing/parsing-sidebar-pane', () => ({ ParsingSidebarPane: () => null }))
vi.mock('@/components/parsing/parsing-active-file-pane', () => ({ ParsingActiveFilePane: () => null }))
vi.mock('@/components/parsing/parsing-library-preview-pane', () => ({ ParsingLibraryPreviewPane: () => null }))
vi.mock('@/components/parsing/parsing-mobile-inspector-content', () => ({ ParsingMobileInspectorContent: () => null }))
vi.mock('@/components/parsing/parsing-mobile-queue-content', () => ({ ParsingMobileQueueContent: () => null }))
vi.mock('@/lib/api', () => ({ documentApi: { patchPipeline: vi.fn(), retry: vi.fn() } }))
vi.mock('@/lib/api/documents', () => ({ documentApi: { patchPipeline: vi.fn(), retry: vi.fn() } }))
vi.mock('@/store/use-parsed-files-store', () => ({ ROOT_FOLDER_ID: 'root' }))

import { ParsingLeftPanel } from './parsing-left-panel'
import { ParsingWorkbenchShell } from './parsing-workbench-shell'

const cleanups: Array<() => void> = []

function inspectorProps(): Parameters<typeof ParsingWorkbenchShell>[0] {
  const noop = () => {}
  return {
    activeBlockId: null,
    activeBlocksWithPositions: [],
    activeFile: null,
    activeFileId: null,
    activeFolderId: 'root',
    activeLibraryFile: null,
    activeLibraryFileId: null,
    activeLibrarySourceStatus: 'unknown',
    activeMarkdown: '',
    availableDatasets: [],
    activeElements: [],
    activePdfQuality: null,
    activeQualityGate: null,
    activeRun: null,
    copied: false,
    copyMarkdown: async () => {},
    currentFolderId: 'root',
    dragOverFolderId: null,
    downloadMarkdown: noop,
    editedContent: '',
    fileInputRef: React.createRef(),
    files: [],
    folderInputRef: React.createRef(),
    folderPathById: { root: 'root' },
    folders: [],
    handleCancelEdit: noop,
    handleDeleteFolder: noop,
    handleFileDragStart: noop,
    handleFileSelect: async () => {},
    handleFolderDragLeave: noop,
    handleFolderDragOver: noop,
    handleFolderDrop: noop,
    handleRebindFileSelect: async () => {},
    handleSaveEdit: async () => {},
    handleSelectRun: noop,
    handleStartEdit: noop,
    handleSubmitToGovernance: noop,
    hoveredBlockId: null,
    imageCaptionEnabled: false,
    imageOcrEnabled: false,
    inspectorOpen: false,
    isEditing: false,
    isLibraryLoaded: true,
    isPdf: false,
    isQueueRehydrating: false,
    isSidebarCollapsed: false,
    libraryFiles: [],
    moveFileToFolder: noop,
    parseAllPending: async () => {},
    parseFile: noop,
    parserBackend: 'auto',
    pdfPreviewResetToken: 0,
    previewMode: 'raw',
    queueOpen: false,
    rebindInputRef: React.createRef(),
    removeFile: noop,
    requestRebindForLibraryFile: noop,
    requestUploadFolder: noop,
    requestUploadToFolder: noop,
    restoreLibraryFileFromCache: async () => {},
    rightPanelMode: 'blocks',
    setActiveBlockId: noop,
    setActiveFileId: noop,
    setActiveFolderId: noop,
    setActiveLibraryFileId: noop,
    setEditedContent: noop,
    setHoveredBlockId: noop,
    setImageCaptionEnabled: noop,
    setImageOcrEnabled: noop,
    setInspectorOpen: noop,
    setIsSidebarCollapsed: noop,
    setParserBackend: noop,
    setPdfPreviewResetToken: noop,
    setPreviewMode: noop,
    setQueueOpen: noop,
    setQueueFileParserBackend: noop,
    setRightPanelMode: noop,
    selectedGovernanceFileIds: new Set(),
    selectedDatasetId: null,
    setVlmCorrectionEnabled: noop,
    onSubmitSelectedToGovernance: noop,
    onToggleGovernanceFileSelection: noop,
    onDatasetScopeChange: noop,
    tocEnabled: false,
    updateParsedFile: noop,
    visibleLibraryOnlyFiles: [],
    visibleQueueFiles: [],
    vlmCorrectionEnabled: false,
  }
}

function mount(element: React.ReactElement) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  let mounted = true
  const unmount = () => {
    if (mounted) {
      mounted = false
      act(() => root.unmount())
      container.remove()
    }
  }
  cleanups.push(unmount)
  act(() => root.render(element))
  return { container, unmount }
}

function startResize(element: Element) {
  act(() =>
    element.dispatchEvent(
      new PointerEvent('pointerdown', { bubbles: true, pointerId: 1, pointerType: 'mouse', button: 0, clientX: 100 }),
    ),
  )
  expect(document.body.style.cursor).toBe('col-resize')
  expect(document.body.style.userSelect).toBe('none')
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  localStorage.clear()
  document.body.style.cursor = 'text'
  document.body.style.userSelect = 'auto'
})

afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
  act(() => window.dispatchEvent(new PointerEvent('pointercancel', { pointerId: 1 })))
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  vi.restoreAllMocks()
})

describe('parsing resize ownership', () => {
  it.each(['left', 'inspector'] as const)('keeps only the latest %s drag owner and its pointerup write', (kind) => {
    const view =
      kind === 'left'
        ? mount(
            <ParsingLeftPanel collapsed={false} onToggleCollapsed={() => {}}>
              content
            </ParsingLeftPanel>,
          )
        : mount(<ParsingWorkbenchShell {...inspectorProps()} />)
    const label = kind === 'left' ? '调整文档列表宽度' : '调整解析信息宽度'
    const storageKey = kind === 'left' ? 'mimirq.parsing.leftPanelWidth' : 'mimirq.parsing.inspectorWidth'
    const writes = vi.spyOn(window.localStorage, 'setItem')
    const slider = view.container.querySelector(`[aria-label="${label}"]`)!
    startResize(slider)
    startResize(slider)

    act(() => window.dispatchEvent(new PointerEvent('pointerup', { pointerId: 1 })))

    expect(document.body.style.cursor).toBe('text')
    expect(document.body.style.userSelect).toBe('auto')
    expect(writes.mock.calls.filter(([key]) => key === storageKey)).toHaveLength(1)
  })

  it('releases the left panel global drag effects when its view unmounts', () => {
    const view = mount(
      <ParsingLeftPanel collapsed={false} onToggleCollapsed={() => {}}>
        content
      </ParsingLeftPanel>,
    )
    startResize(view.container.querySelector('[aria-label="调整文档列表宽度"]')!)

    view.unmount()

    expect(document.body.style.cursor).toBe('text')
    expect(document.body.style.userSelect).toBe('auto')
  })

  it('keeps ordinary pointerup cleanup for the left panel', () => {
    const view = mount(
      <ParsingLeftPanel collapsed={false} onToggleCollapsed={() => {}}>
        content
      </ParsingLeftPanel>,
    )
    startResize(view.container.querySelector('[aria-label="调整文档列表宽度"]')!)
    act(() => window.dispatchEvent(new PointerEvent('pointerup', { pointerId: 1 })))

    expect(document.body.style.cursor).toBe('text')
    expect(document.body.style.userSelect).toBe('auto')
  })

  it('releases the inspector global drag effects when its view unmounts', () => {
    const view = mount(<ParsingWorkbenchShell {...inspectorProps()} />)
    startResize(view.container.querySelector('[aria-label="调整解析信息宽度"]')!)

    view.unmount()

    expect(document.body.style.cursor).toBe('text')
    expect(document.body.style.userSelect).toBe('auto')
  })

  it('keeps ordinary pointerup cleanup for the inspector', () => {
    const view = mount(<ParsingWorkbenchShell {...inspectorProps()} />)
    startResize(view.container.querySelector('[aria-label="调整解析信息宽度"]')!)
    act(() => window.dispatchEvent(new PointerEvent('pointerup', { pointerId: 1 })))

    expect(document.body.style.cursor).toBe('text')
    expect(document.body.style.userSelect).toBe('auto')
  })
})
