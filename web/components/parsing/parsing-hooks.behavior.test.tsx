// @vitest-environment happy-dom

import React, { act, useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ParsedFileData, FolderNode } from '@/store/use-parsed-files-store'
import type { ParsingContentResponse, ParsingElement } from '@/lib/api/parsing'
import type { ParsedFile } from './parsing-types'

const ports = vi.hoisted(() => ({
  parsing: { upload: vi.fn(), parse: vi.fn(), getContent: vi.fn(), updateContent: vi.fn(), listDocuments: vi.fn() },
  documents: { list: vi.fn(), getParsedContent: vi.fn(), download: vi.fn() },
  datasets: { listAll: vi.fn() },
  cache: {
    getDocContentFromCache: vi.fn(),
    getDocSourceFromCache: vi.fn(),
    saveDocSourceToCache: vi.fn(),
    deleteDocContentFromCache: vi.fn(),
    deleteDocSourceFromCache: vi.fn(),
  },
  update: vi.fn(),
  upsert: vi.fn(),
  push: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  currentLibrary: [] as ParsedFileData[],
  translate: (key: string) => key,
}))
vi.mock('@/lib/api', () => ({ parsingApi: ports.parsing, documentApi: ports.documents, datasetApi: ports.datasets }))
vi.mock('@/lib/api/parsing', () => ({ parsingApi: ports.parsing }))
vi.mock('@/lib/api/documents', () => ({ documentApi: ports.documents }))
vi.mock('@/lib/api/datasets', () => ({ datasetApi: ports.datasets }))
vi.mock('@/lib/doc-content-cache', () => ports.cache)
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn(), reportClientWarning: vi.fn() }))
vi.mock('@/store/use-parsed-files-store', () => ({
  ROOT_FOLDER_ID: 'root',
  useParsedFiles: { getState: () => ({ files: ports.currentLibrary }) },
}))
vi.mock('next-intl', () => ({ useTranslations: () => ports.translate }))
vi.mock('@/contexts/pipeline-capabilities-context', () => ({
  usePipelineCapabilities: () => ({ capabilities: null, parserBackendAvailable: () => undefined }),
}))
vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ push: ports.push }) }))
vi.mock('sonner', () => ({ toast: ports.toast }))

import { ParserBackendProvider } from '@/contexts/parser-backend-context'
import { useParsingPageState } from './use-parsing-page-state'
import { useParsingLibraryActions } from './use-parsing-library-actions'
import { useParsingViewState } from './use-parsing-view-state'
import { useParsingRunActions } from './use-parsing-run-actions'
import { useParsingEditorActions } from './use-parsing-editor-actions'
import { bumpParsingProgress, countMarkdownHeadings, mapBackendStatusToLibraryStatus } from './parsing-page-utils'

// The original hooks accept these same production helpers as options. Keeping the
// spread lets the identical cases replay against their frozen original owners.
const originalHelperOptions = { bumpParsingProgress, countMarkdownHeadings, mapBackendStatusToLibraryStatus }
const cleanups: Array<() => void> = []

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function queuedFile(overrides: Partial<ParsedFile> = {}): ParsedFile {
  const file = new File(['source'], 'report.pdf', { type: 'application/pdf' })
  return {
    id: 'queue-a',
    file,
    folderId: 'root',
    name: file.name,
    size: file.size,
    status: 'pending',
    markdownContent: null,
    parserBackend: 'auto',
    parserLabel: 'Auto',
    libraryId: 'library-a',
    createdAt: 10,
    ...overrides,
  }
}

function libraryFile(overrides: Partial<ParsedFileData> = {}): ParsedFileData {
  return {
    id: 'library-a',
    filename: 'report.pdf',
    fileType: 'pdf',
    fileSize: 6,
    markdownContent: '',
    originalMarkdownContent: '',
    parsedAt: '2026-11-05T00:00:00Z',
    parser: 'Auto',
    folderId: 'root',
    status: 'parsed',
    source: 'parsing_workspace',
    ...overrides,
  }
}

function content(overrides: Partial<ParsingContentResponse> = {}): ParsingContentResponse {
  return {
    document_id: 'library-a',
    parser_backend: 'auto',
    markdown_content: '# Heading\nbody\n## Second\n####### not a heading\n#missing-space',
    original_markdown_content: '# Heading\nbody\n## Second\n####### not a heading\n#missing-space',
    ...overrides,
  }
}

function mount(options: { files?: ParsedFile[]; library?: ParsedFileData[]; loaded?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)

  function useHarness() {
    const [files, setFiles] = useState(options.files || [])
    const [libraryFiles, setLibraryFiles] = useState(options.library || [])
    const [folders, setFolders] = useState<FolderNode[]>([])
    const [activeFolderId, setActiveFolderId] = useState('root')
    const [selectedGovernanceFileIds, setSelectedGovernanceFileIds] = useState<Set<string>>(new Set())
    const page = useParsingPageState({ files, setFiles })
    ports.currentLibrary = libraryFiles

    const updateParsedFile = useCallback(async (id: string, updates: Partial<Omit<ParsedFileData, 'id'>>) => {
      ports.update(id, updates)
      setLibraryFiles((previous) => previous.map((file) => (file.id === id ? { ...file, ...updates } : file)))
    }, [])
    const upsertParsedFile = useCallback((file: ParsedFileData) => {
      ports.upsert(file)
      setLibraryFiles((previous) => [...previous.filter((item) => item.id !== file.id), file])
    }, [])
    const createFolder = useCallback((name: string, parentId = 'root') => {
      const id = `${parentId}/${name}`
      setFolders((previous) => [...previous, { id, name, parentId, createdAt: '2026-11-05T00:00:00Z' }])
      return id
    }, [])
    const library = useParsingLibraryActions({
      ...page,
      ...originalHelperOptions,
      activeFolderId,
      createFolder,
      folders,
      libraryFiles,
      setActiveFolderId,
      setFiles,
      updateParsedFile,
      upsertParsedFile,
    })
    const view = useParsingViewState({
      ...page,
      ...originalHelperOptions,
      activeFolderId,
      files,
      folders,
      isLibraryLoaded: options.loaded || false,
      libraryFiles,
      mountLibraryFileToQueue: library.mountLibraryFileToQueue,
      setParsedFiles: setLibraryFiles,
      updateParsedFile,
    })
    const run = useParsingRunActions({
      ...page,
      ...view,
      ...originalHelperOptions,
      setFiles,
      updateParsedFile,
      upsertParsedFile,
    })
    const editor = useParsingEditorActions({
      ...page,
      ...view,
      ...originalHelperOptions,
      addParsedFile: () => 'added-library',
      files,
      libraryFiles,
      selectedGovernanceFileIds,
      setSelectedGovernanceFileIds,
      setFiles,
      updateParsedFile,
    })
    return { files, libraryFiles, page, library, view, run, editor, setFiles, setActiveFolderId }
  }

  let snapshot!: ReturnType<typeof useHarness>
  function Harness() {
    snapshot = useHarness()
    return null
  }
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <ParserBackendProvider>
          <Harness />
        </ParserBackendProvider>
      </QueryClientProvider>,
    ),
  )
  cleanups.push(() => {
    act(() => root.unmount())
    client.clear()
    container.remove()
  })
  return { current: () => snapshot, client }
}

async function settle() {
  await act(async () => {})
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5)
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5)
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  vi.clearAllMocks()
  localStorage.clear()
  ports.currentLibrary = []
  ports.parsing.upload.mockReset()
  ports.parsing.parse.mockReset()
  ports.parsing.getContent.mockReset().mockResolvedValue(content())
  ports.parsing.updateContent.mockReset().mockResolvedValue(content())
  ports.parsing.listDocuments.mockReset().mockResolvedValue({ items: [] })
  ports.documents.list.mockReset().mockResolvedValue({ items: [] })
  ports.datasets.listAll.mockReset().mockResolvedValue([{ id: 'dataset-a', name: 'Dataset A' }])
  ports.documents.getParsedContent.mockReset()
  ports.cache.getDocContentFromCache.mockReset().mockResolvedValue(null)
  ports.cache.getDocSourceFromCache.mockReset().mockResolvedValue(null)
})

afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
  vi.useRealTimers()
})

describe('shared parsing helper contracts', () => {
  it('preserves parse options, progress cap, stats, quality, history, persistence and cleanup', async () => {
    const response = deferred<ParsingContentResponse>()
    ports.parsing.parse.mockReturnValueOnce(response.promise)
    const view = mount({ files: [queuedFile()], library: [libraryFile()] })
    act(() => {
      view.current().page.setImageCaptionEnabled(true)
      view.current().page.setImageOcrEnabled(true)
      view.current().page.setVlmCorrectionEnabled(true)
    })
    let request!: Promise<void>
    act(() => {
      request = view.current().run.parseFile('queue-a', 'marker')
    })
    const controller = view.current().page.parseControllersRef.current.get('queue-a')!
    expect(ports.parsing.parse).toHaveBeenCalledWith('library-a', {
      parser_backend: 'marker',
      image_caption_enabled: true,
      image_ocr_enabled: true,
      vlm_correction_enabled: true,
      signal: controller.signal,
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })
    expect(view.current().files[0]).toMatchObject({ status: 'parsing', progress: 90 })

    const elements: ParsingElement[] = [{ id: 'element-a', kind: 'paragraph', page: 1, text: 'Heading' }]
    const result = content({
      parser_backend: 'marker',
      parse_duration_sec: 2.5,
      stats: { page_count: 4, table_count: 3, image_count: 2, block_count: 9 },
      elements,
      pdf_quality: {
        score: 1,
        text_quality_score: 1,
        format_consistency_score: 1,
        table_quality_score: 1,
        page_count: 4,
        is_scanned: false,
      },
      quality_gate: { grade: 'pass', reasons: [] },
    })
    await act(async () => {
      response.resolve(result)
      await request
    })

    expect(view.current().files[0]).toMatchObject({
      status: 'parsed',
      progress: 100,
      duration: 2.5,
      parserBackend: 'marker',
      elements,
      pdfQuality: result.pdf_quality,
      qualityGate: result.quality_gate,
      stats: { headingCount: 2, pageCount: 4, tableCount: 3, imageCount: 2, blockCount: 9 },
    })
    expect(view.current().files[0].runs).toHaveLength(1)
    expect(view.current().files[0].runs![0]).toMatchObject({ rawMarkdown: result.original_markdown_content, elements })
    expect(view.current().page.rightPanelMode).toBe('markdown')
    expect(ports.update).toHaveBeenLastCalledWith(
      'library-a',
      expect.objectContaining({
        markdownContent: result.markdown_content,
        originalMarkdownContent: result.original_markdown_content,
        parserBackend: 'marker',
        durationSec: 2.5,
        status: 'parsed',
        folderId: 'root',
      }),
    )
    expect(view.current().page.parseControllersRef.current.size).toBe(0)
    expect(view.current().page.parseProgressIntervalsRef.current.size).toBe(0)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600)
    })
    expect(view.current().files[0].progress).toBe(100)
  })

  it('uploads a missing library source with the selected dataset and maps backend status before parsing', async () => {
    ports.parsing.upload.mockResolvedValue({
      id: 'created-a',
      status: 'processing',
      metadata: { target_dataset_id: 'dataset-a', target_dataset_name: 'Dataset A' },
    })
    ports.parsing.parse.mockResolvedValue(content({ pdf_quality: null, quality_gate: null }))
    const file = queuedFile({ libraryId: undefined, datasetId: 'dataset-a' })
    const view = mount({ files: [file] })
    await act(async () => {
      await view.current().run.parseFile(file.id)
    })
    expect(ports.parsing.upload).toHaveBeenCalledWith(file.file, { parser_backend: 'auto', dataset_id: 'dataset-a' })
    expect(ports.upsert).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'created-a', status: 'parsing', datasetId: 'dataset-a', datasetName: 'Dataset A' }),
    )
    expect(view.current().files[0]).toMatchObject({
      libraryId: 'created-a',
      status: 'parsed',
      pdfQuality: null,
      qualityGate: null,
    })
  })

  it('publishes parse diagnostics on failure and releases the original resources', async () => {
    const response = deferred<ParsingContentResponse>()
    ports.parsing.parse.mockReturnValue(response.promise)
    const view = mount({ files: [queuedFile()], library: [libraryFile()] })
    let request!: Promise<void>
    act(() => {
      request = view.current().run.parseFile('queue-a')
    })
    const diagnostics = { error_type: 'parse_error', suggested_backends: ['marker'] }
    await act(async () => {
      response.reject({ response: { data: { detail: { message: 'parse rejected', diagnostics } } } })
      await request
    })
    expect(view.current().files[0]).toMatchObject({ status: 'error', progress: 0, parseDiagnostics: diagnostics })
    expect(ports.update).toHaveBeenLastCalledWith(
      'library-a',
      expect.objectContaining({ status: 'error', parserBackend: 'auto' }),
    )
    expect(view.current().page.parseControllersRef.current.size).toBe(0)
    expect(view.current().page.parseProgressIntervalsRef.current.size).toBe(0)
  })

  it('keeps a newer parse owner and ignores the retired response and its cleanup', async () => {
    const first = deferred<ParsingContentResponse>()
    const second = deferred<ParsingContentResponse>()
    ports.parsing.parse.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const view = mount({ files: [queuedFile()], library: [libraryFile()] })
    let oldRequest!: Promise<void>
    let newRequest!: Promise<void>
    act(() => {
      oldRequest = view.current().run.parseFile('queue-a')
    })
    const oldController = view.current().page.parseControllersRef.current.get('queue-a')!
    act(() => {
      newRequest = view.current().run.parseFile('queue-a', 'marker')
    })
    const currentController = view.current().page.parseControllersRef.current.get('queue-a')!
    expect(oldController.signal.aborted).toBe(true)
    await act(async () => {
      first.resolve(content({ markdown_content: 'retired result' }))
      await oldRequest
    })
    expect(view.current().files[0]).toMatchObject({ status: 'parsing', parserBackend: 'marker', markdownContent: null })
    expect(view.current().page.parseControllersRef.current.get('queue-a')).toBe(currentController)
    expect(view.current().page.parseProgressIntervalsRef.current.size).toBe(1)
    await act(async () => {
      second.resolve(content({ parser_backend: 'marker' }))
      await newRequest
    })
    expect(view.current().files[0]).toMatchObject({ status: 'parsed', parserBackend: 'marker' })
    expect(view.current().files[0].runs).toHaveLength(1)
    expect(view.current().page.parseControllersRef.current.size).toBe(0)
    expect(view.current().page.parseProgressIntervalsRef.current.size).toBe(0)
  })

  it('saves edited markdown with the existing heading policy and updates only the selected run', async () => {
    const edited = '# First\n## Second\n####### excluded\n#missing-space'
    const file = queuedFile({
      status: 'parsed',
      markdownContent: '# Original',
      activeRunId: 'selected',
      stats: { charCount: 10, lineCount: 1, headingCount: 1, pageCount: 4, blockCount: 2 },
      runs: [
        {
          id: 'other',
          parserBackend: 'auto',
          parserLabel: 'Auto',
          rawMarkdown: 'other',
          cleanedMarkdown: 'other',
          blocks: [],
          createdAt: 1,
        },
        {
          id: 'selected',
          parserBackend: 'auto',
          parserLabel: 'Auto',
          rawMarkdown: '# Original',
          cleanedMarkdown: '# Original',
          blocks: [],
          createdAt: 2,
        },
      ],
    })
    ports.parsing.updateContent.mockResolvedValue(
      content({ markdown_content: edited, original_markdown_content: edited }),
    )
    const view = mount({ files: [file], library: [libraryFile()] })
    act(() => view.current().editor.handleStartEdit())
    act(() => view.current().page.setEditedContent(edited))
    await act(async () => {
      await view.current().editor.handleSaveEdit()
    })
    expect(ports.parsing.updateContent).toHaveBeenCalledWith('library-a', { markdown_content: edited })
    expect(view.current().files[0]).toMatchObject({
      governanceStatus: 'ready',
      markdownContent: edited,
      stats: { charCount: edited.length, lineCount: 4, headingCount: 2, blockCount: 0, pageCount: 4 },
    })
    expect(view.current().files[0].runs![0]).toEqual(file.runs![0])
    expect(view.current().files[0].runs![1]).toMatchObject({ rawMarkdown: edited, cleanedMarkdown: edited, blocks: [] })
    expect(view.current().page.isEditing).toBe(false)
    expect(view.current().page.editSession).toBeNull()
    expect(view.current().page.rightPanelMode).toBe('markdown')
    expect(ports.update).toHaveBeenCalledWith(
      'library-a',
      expect.objectContaining({
        markdownContent: edited,
        originalMarkdownContent: edited,
        governanceStatus: 'ready',
        status: 'parsed',
      }),
    )
  })

  it('restores knowledge content using unchanged persisted metadata, element filtering and heading statistics', async () => {
    const element = { id: 'element-a', kind: 'paragraph', page: 1, text: 'remote' }
    ports.documents.getParsedContent.mockResolvedValue({
      available: true,
      markdown_content: '  # Remote\n## Second  ',
      original_markdown_content: '# Remote\n## Second',
      persisted_meta: {
        parser_backend: ' marker ',
        parse_duration_sec: '3.5',
        elements: [null, 4, element, []],
      },
    })
    const view = mount({
      library: [libraryFile({ source: 'knowledge_base', datasetId: 'dataset-a', datasetName: 'Dataset A' })],
    })
    await act(async () => {
      await view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file, { forceRefresh: true })
    })
    expect(ports.documents.getParsedContent).toHaveBeenCalledWith('library-a', { max_chars: 2_000_000 })
    expect(ports.update).toHaveBeenCalledWith(
      'library-a',
      expect.objectContaining({ parserBackend: 'marker', durationSec: 3.5, elements: [element, []] }),
    )
    expect(view.current().files[0]).toMatchObject({
      status: 'parsed',
      markdownContent: '# Remote\n## Second',
      librarySource: 'knowledge_base',
      datasetId: 'dataset-a',
      elements: [element, []],
      stats: { headingCount: 2 },
    })
    expect(view.current().page.autoParseFileId).toBeNull()
  })

  it('syncs real queries with the original dataset scope, status mapping and knowledge duplicate policy', async () => {
    const element = { id: 'element-a', kind: 'paragraph', page: 1, text: 'mapped' }
    ports.parsing.listDocuments.mockResolvedValue({
      items: [
        {
          id: 'parsing-a',
          filename: 'report.pdf',
          status: 'processing',
          metadata: { target_dataset_id: ' dataset-a ', parser_backend: ' marker ', elements: [false, element] },
        },
      ],
    })
    ports.documents.list.mockResolvedValue({
      items: [
        { id: 'duplicate', filename: 'duplicate.pdf', status: 'completed', metadata: { workspace: 'parsing' } },
        {
          id: 'knowledge-a',
          filename: 'knowledge.pdf',
          status: 'failed',
          dataset_id: 'dataset-a',
          error_message: 'knowledge failed',
          metadata: { source_path: 'folder/knowledge.pdf' },
        },
      ],
    })
    const view = mount({ loaded: true })
    act(() => view.current().page.setSelectedDatasetId('dataset-a'))
    await settle()
    expect(ports.parsing.listDocuments).toHaveBeenCalledWith({ skip: 0, limit: 200, dataset_id: 'dataset-a' })
    expect(ports.documents.list).toHaveBeenCalledWith({ skip: 0, limit: 200, dataset_id: 'dataset-a' })
    expect(view.current().libraryFiles).toHaveLength(2)
    expect(view.current().libraryFiles).toContainEqual(
      expect.objectContaining({
        id: 'parsing-a',
        status: 'parsing',
        parserBackend: 'marker',
        datasetId: 'dataset-a',
        datasetName: 'Dataset A',
        elements: [element],
      }),
    )
    expect(view.current().libraryFiles).toContainEqual(
      expect.objectContaining({
        id: 'knowledge-a',
        source: 'knowledge_base',
        status: 'error',
        error: 'knowledge failed',
        datasetName: 'Dataset A',
        sourcePath: 'folder/knowledge.pdf',
      }),
    )
    expect(view.current().page.didSyncLibraryFromServerRef.current).toBe(true)
  })
})

describe('directory upload dataset ownership', () => {
  it.each(['plain', 'directory'])(
    'keeps a failed %s upload visible in its selected dataset for retry',
    async (kind) => {
      ports.parsing.upload.mockRejectedValue(new Error('upload rejected'))
      const view = mount()
      act(() => view.current().page.setSelectedDatasetId('dataset-a'))
      const file = new File(['source'], 'report.md', { type: 'text/markdown' })
      if (kind === 'directory') Object.defineProperty(file, 'webkitRelativePath', { value: 'folder/report.md' })
      await act(async () => {
        await view.current().library.addFiles([file])
      })
      expect(ports.parsing.upload).toHaveBeenCalledWith(file, {
        parser_backend: expect.any(String),
        dataset_id: 'dataset-a',
      })
      expect({
        status: view.current().files[0].status,
        datasetId: view.current().files[0].datasetId,
        visibleCount: view.current().view.visibleQueueFiles.length,
        activeFileId: view.current().page.activeFileId,
      }).toEqual({ status: 'error', datasetId: 'dataset-a', visibleCount: 1, activeFileId: view.current().files[0].id })
    },
  )

  it('keeps successful directory uploads visible with the server dataset metadata', async () => {
    ports.parsing.upload.mockResolvedValue({
      id: 'uploaded-a',
      status: 'completed',
      metadata: { target_dataset_id: ' dataset-a ', target_dataset_name: ' Dataset A ' },
    })
    const view = mount()
    act(() => view.current().page.setSelectedDatasetId('dataset-a'))
    const file = new File(['source'], 'report.md', { type: 'text/markdown' })
    Object.defineProperty(file, 'webkitRelativePath', { value: 'folder/report.md' })
    await act(async () => {
      await view.current().library.addFiles([file])
    })
    expect(view.current().files[0]).toMatchObject({
      libraryId: 'uploaded-a',
      datasetId: 'dataset-a',
      datasetName: 'Dataset A',
      sourcePath: 'folder/report.md',
    })
    expect(view.current().view.visibleQueueFiles).toHaveLength(1)
    expect(ports.upsert).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'uploaded-a', datasetId: 'dataset-a', status: 'parsed' }),
    )
  })
})
