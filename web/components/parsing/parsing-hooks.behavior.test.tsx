// @vitest-environment happy-dom

import React, { act, useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ParsedFileData, FolderNode } from '@/store/use-parsed-files-store'
import type { ParsingContentResponse, ParsingElement } from '@/lib/api/parsing'
import type { ParsedFile } from './parsing-types'
import type { Document } from '@/types/backend'
import JSZip from 'jszip'

const ports = vi.hoisted(() => ({
  parsing: {
    upload: vi.fn(),
    parse: vi.fn(),
    getContent: vi.fn(),
    updateContent: vi.fn(),
    listDocuments: vi.fn(),
    delete: vi.fn(),
  },
  documents: {
    list: vi.fn(),
    get: vi.fn(),
    getParsedContent: vi.fn(),
    download: vi.fn(),
    delete: vi.fn(),
    patchPipeline: vi.fn(),
    retry: vi.fn(),
  },
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
  replace: vi.fn(),
  remove: vi.fn(),
  moveFolder: vi.fn(),
  push: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  currentLibrary: [] as ParsedFileData[],
  currentFolders: [] as FolderNode[],
  libraryError: undefined as unknown,
  authScope: 'initial-scope',
  authRevision: 0,
  translate: (key: string) => key,
}))
vi.mock('@/lib/api/parsing', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/parsing')>()),
  parsingApi: ports.parsing,
}))
vi.mock('@/lib/api/documents', () => ({ documentApi: ports.documents }))
vi.mock('@/lib/api/datasets', () => ({ datasetApi: ports.datasets }))
vi.mock('@/lib/doc-content-cache', () => ports.cache)
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn(), reportClientWarning: vi.fn() }))
vi.mock('@/lib/auth-storage', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/auth-storage')>()),
  getAuthCacheScope: () => ports.authScope,
  getAuthSessionRevision: () => ports.authRevision,
}))
vi.mock('@/store/use-parsed-files-store', () => ({
  ROOT_FOLDER_ID: 'root',
  useParsedFiles: {
    getState: () => ({ files: ports.currentLibrary, folders: ports.currentFolders, loadError: ports.libraryError }),
  },
}))
vi.mock('next-intl', () => ({ useTranslations: () => ports.translate }))
vi.mock('@/contexts/pipeline-capabilities-context', () => ({
  usePipelineCapabilities: () => ({ capabilities: null, parserBackendAvailable: () => undefined }),
}))
vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ push: ports.push }) }))
vi.mock('sonner', () => ({ toast: ports.toast }))

import { getParserLabel } from '@/lib/parser-options'
import { ParserBackendProvider } from '@/contexts/parser-backend-context'
import { useParsingPageState } from './use-parsing-page-state'
import { useParsingLibraryActions } from './use-parsing-library-actions'
import { useParsingViewState } from './use-parsing-view-state'
import { useParsingRunActions } from './use-parsing-run-actions'
import { useParsingEditorActions } from './use-parsing-editor-actions'
import { useParsingQueueActions } from './use-parsing-queue-actions'

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
    librarySource: 'parsing_workspace',
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
    edited: false,
    ...overrides,
  }
}

// Only the fields consumed by this Hook's list mapping are mocked here.
function remoteDocument(id: string, overrides: Partial<Document> = {}) {
  return {
    id,
    filename: `${id}.md`,
    file_type: 'md',
    file_size: 0,
    status: 'completed' as const,
    created_at: '2026-11-13T00:00:00Z',
    updated_at: '2026-11-13T00:00:00Z',
    dataset_id: null,
    metadata: {},
    ...overrides,
  }
}

function mount(options: { files?: ParsedFile[]; library?: ParsedFileData[]; loaded?: boolean; strict?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)

  function useHarness() {
    const [files, setFiles] = useState(options.files ?? [])
    const [libraryFiles, setLibraryFiles] = useState(options.library ?? [])
    const [folders, setFolders] = useState<FolderNode[]>([])
    const [activeFolderId, setActiveFolderId] = useState('root')
    const [isLibraryLoaded, setLibraryLoaded] = useState(options.loaded ?? false)
    const [selectedGovernanceFileIds, setSelectedGovernanceFileIds] = useState<Set<string>>(new Set())
    const page = useParsingPageState({ files, setFiles })
    ports.currentLibrary = libraryFiles
    ports.currentFolders = folders

    const updateParsedFile = useCallback(
      async (
        ...args: [id: string, updates: Partial<Omit<ParsedFileData, 'id'>>, options?: { requirePersistence?: boolean }]
      ) => {
        const [id, updates] = args
        await ports.update(...args)
        ports.currentLibrary = ports.currentLibrary.map((file) => (file.id === id ? { ...file, ...updates } : file))
        setLibraryFiles(ports.currentLibrary)
      },
      [],
    )
    const upsertParsedFile = useCallback((file: ParsedFileData) => {
      ports.upsert(file)
      ports.currentLibrary = [...ports.currentLibrary.filter((item) => item.id !== file.id), file]
      setLibraryFiles(ports.currentLibrary)
    }, [])
    const replaceParsedFile = useCallback((id: string, file: ParsedFileData) => {
      ports.replace(id, file)
      ports.currentLibrary = ports.currentLibrary
        .filter((entry) => entry.id !== file.id)
        .map((entry) => (entry.id === id ? { ...entry, ...file, folderId: entry.folderId } : entry))
      setLibraryFiles(ports.currentLibrary)
    }, [])
    const createFolder = useCallback((name: string, parentId = 'root') => {
      const id = `${parentId}/${name}`
      ports.currentFolders = [...ports.currentFolders, { id, name, parentId, createdAt: '2026-11-05T00:00:00Z' }]
      setFolders(ports.currentFolders)
      return id
    }, [])
    const removeParsedFile = useCallback((id: string) => {
      ports.remove(id)
      ports.currentLibrary = ports.currentLibrary.filter((file) => file.id !== id)
      setLibraryFiles(ports.currentLibrary)
    }, [])
    const library = useParsingLibraryActions({
      ...page,
      activeFolderId,
      createFolder,
      isLibraryLoaded,
      libraryFiles,
      removeParsedFile,
      setActiveFolderId,
      setFiles,
      updateParsedFile,
      upsertParsedFile,
    })
    const view = useParsingViewState({
      ...page,
      activeFolderId,
      files,
      folders,
      isLibraryLoaded,
      libraryFiles,
      setParsedFiles: setLibraryFiles,
      updateParsedFile,
    })
    const run = useParsingRunActions({
      restoreLibraryFileFromCache: library.restoreLibraryFileFromCache,
      ...page,
      ...view,
      setFiles,
      updateParsedFile,
      upsertParsedFile,
      replaceParsedFile,
      removeParsedFile,
      setSelectedGovernanceFileIds,
    })
    const editor = useParsingEditorActions({
      ...page,
      ...view,
      libraryFiles,
      selectedGovernanceFileIds,
      setSelectedGovernanceFileIds,
      setFiles,
      updateParsedFile,
    })
    const queue = useParsingQueueActions({
      ...page,
      moveFolder: ports.moveFolder,
      removeParsedFile,
      setSelectedGovernanceFileIds,
      setFiles,
      updateParsedFile,
    })
    return {
      files,
      libraryFiles,
      page,
      library,
      view,
      run,
      editor,
      queue,
      setFiles,
      setLibraryFiles,
      setFolders,
      setActiveFolderId,
      setLibraryLoaded,
      sourceStatus: view.activeLibrarySourceStatus,
      selectedGovernanceFileIds,
      setSelectedGovernanceFileIds,
    }
  }

  let snapshot!: ReturnType<typeof useHarness>
  function Harness() {
    snapshot = useHarness()
    return null
  }
  const element = (
    <QueryClientProvider client={client}>
      <ParserBackendProvider>
        <Harness />
      </ParserBackendProvider>
    </QueryClientProvider>
  )
  act(() => root.render(options.strict ? <React.StrictMode>{element}</React.StrictMode> : element))
  cleanups.push(() => {
    act(() => root.unmount())
    client.clear()
    container.remove()
  })
  return { current: () => snapshot, client, unmount: () => act(() => root.unmount()) }
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
  ports.currentFolders = []
  ports.libraryError = undefined
  ports.authScope = 'initial-scope'
  ports.authRevision = 0
  ports.update.mockReset().mockResolvedValue(undefined)
  ports.parsing.upload.mockReset()
  ports.parsing.delete.mockReset().mockResolvedValue(undefined)
  ports.documents.delete.mockReset().mockResolvedValue(undefined)
  ports.documents.patchPipeline.mockReset().mockResolvedValue(undefined)
  ports.documents.retry.mockReset().mockResolvedValue(undefined)
  ports.remove.mockReset()
  ports.upsert.mockReset()
  ports.replace.mockReset()
  ports.moveFolder.mockReset()
  ports.parsing.parse.mockReset()
  ports.parsing.getContent.mockReset().mockResolvedValue(content())
  ports.parsing.updateContent.mockReset().mockResolvedValue(content())
  ports.parsing.listDocuments.mockReset().mockResolvedValue({ total: 0, items: [] })
  ports.documents.list.mockReset().mockResolvedValue({ total: 0, items: [] })
  ports.documents.get.mockReset().mockResolvedValue({ status: 'completed', error_message: null })
  ports.datasets.listAll.mockReset().mockResolvedValue([{ id: 'dataset-a', name: 'Dataset A' }])
  ports.documents.getParsedContent.mockReset()
  ports.cache.getDocContentFromCache.mockReset().mockResolvedValue(null)
  ports.cache.getDocSourceFromCache.mockReset().mockResolvedValue(null)
  ports.cache.saveDocSourceToCache.mockReset().mockResolvedValue(undefined)
})

afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
  vi.useRealTimers()
})

describe('library synchronization ownership', () => {
  it('preserves a remote entry acknowledged after the listing started', async () => {
    const listing = deferred<{ total: 0; items: [] }>()
    ports.parsing.listDocuments.mockReturnValue(listing.promise)
    const previous = libraryFile()
    const added = libraryFile({ id: 'new-upload', markdownContent: 'new upload' })
    const view = mount({ loaded: true, library: [previous] })
    await settle()
    act(() => view.current().setLibraryFiles((files) => [...files, added]))
    await act(async () => listing.resolve({ total: 0, items: [] }))
    await settle()

    expect(view.current().libraryFiles).toEqual([added])
  })

  it('does not resurrect an entry removed while the listing was pending', async () => {
    const document = remoteDocument('library-a')
    const listing = deferred<{ total: number; items: (typeof document)[] }>()
    ports.parsing.listDocuments.mockReturnValue(listing.promise)
    const view = mount({ loaded: true, library: [libraryFile()] })
    await settle()
    act(() => view.current().setLibraryFiles([]))
    await act(async () => listing.resolve({ total: 1, items: [document] }))
    await settle()

    expect(view.current().libraryFiles).toEqual([])
  })

  it('does not overwrite edits made while the listing was pending', async () => {
    const document = remoteDocument('library-a')
    const listing = deferred<{ total: number; items: (typeof document)[] }>()
    ports.parsing.listDocuments.mockReturnValue(listing.promise)
    const view = mount({ loaded: true, library: [libraryFile()] })
    await settle()
    const updated = libraryFile({ markdownContent: 'new saved edit', governanceStatus: 'ready' })
    act(() => view.current().setLibraryFiles([updated]))
    await act(async () => listing.resolve({ total: 1, items: [document] }))
    await settle()

    expect(view.current().libraryFiles).toEqual([updated])
  })

  it('keeps real local files while removing remote-owned entries absent from complete successful lists', async () => {
    const local = libraryFile({ id: 'preview-local', source: undefined, markdownContent: '# Local preview' })
    const view = mount({
      loaded: true,
      library: [local, libraryFile(), libraryFile({ id: 'knowledge-old', source: 'knowledge_base' })],
    })
    await settle()

    expect(view.current().libraryFiles).toEqual([local])
  })

  it('retains the failed source and local entries while refreshing the available source and exposing retry', async () => {
    ports.parsing.listDocuments.mockRejectedValue(new Error('Parsing source unavailable'))
    ports.documents.list.mockResolvedValue({ total: 1, items: [remoteDocument('knowledge-new')] })
    const local = libraryFile({ id: 'preview-local', source: undefined })
    const parsing = libraryFile()
    const view = mount({
      loaded: true,
      library: [local, parsing, libraryFile({ id: 'knowledge-old', source: 'knowledge_base' })],
    })
    await settle()

    expect(view.current().libraryFiles.map((file) => file.id)).toEqual(['preview-local', 'library-a', 'knowledge-new'])
    expect(view.current().view.librarySyncError).toBeInstanceOf(Error)

    ports.parsing.listDocuments.mockResolvedValue({ total: 0, items: [] })
    act(() => view.current().view.retryLibrarySync())
    await settle()
    expect(view.current().view.librarySyncError).toBeNull()
    expect(view.current().libraryFiles.map((file) => file.id)).toEqual(['preview-local', 'knowledge-new'])
  })

  it('reads beyond the first server page before reconciling the shared library', async () => {
    const documents = Array.from({ length: 201 }, (_, index) => remoteDocument(`document-${index}`))
    ports.parsing.listDocuments.mockImplementation(({ skip, limit }: { skip: number; limit: number }) =>
      Promise.resolve({ total: documents.length, items: documents.slice(skip, skip + limit) }),
    )
    const view = mount({ loaded: true })
    await settle()

    expect(view.current().libraryFiles).toHaveLength(201)
    expect(ports.parsing.listDocuments).toHaveBeenCalledWith({ skip: 200, limit: 200 }, expect.anything())
  })

  it('preserves checked governance metadata and valid zero values when refreshing an existing record', async () => {
    ports.parsing.listDocuments.mockResolvedValue({ total: 1, items: [remoteDocument('library-a')] })
    const review = { qualityScore: 0, issues: [], annotations: [], tags: ['kept'], category: null }
    const view = mount({
      loaded: true,
      library: [
        libraryFile({
          fileSize: 6,
          markdownContent: 'saved edit',
          governanceReview: review,
          governanceStatus: 'ready',
        }),
      ],
    })
    await settle()

    expect(view.current().libraryFiles[0]).toMatchObject({
      fileSize: 0,
      markdownContent: 'saved edit',
      governanceReview: review,
      governanceStatus: 'ready',
    })
  })
})

describe('library restoration boundary', () => {
  it('keeps current files when an earlier listing completes after restoration becomes unavailable', async () => {
    const listing = deferred<{ items: []; total: 0 }>()
    ports.parsing.listDocuments.mockReturnValue(listing.promise)
    const file = libraryFile({ markdownContent: '# Kept local file' })
    const view = mount({ loaded: true, library: [file] })
    await settle()
    expect(ports.parsing.listDocuments).toHaveBeenCalled()

    act(() => view.current().setLibraryLoaded(false))
    await act(async () => listing.resolve({ items: [], total: 0 }))
    await settle()

    expect(view.current().libraryFiles).toEqual([file])
  })

  it('does not apply an earlier content response after restoration becomes unavailable', async () => {
    const listing = deferred<{ items: []; total: 0 }>()
    const response = deferred<ParsingContentResponse>()
    ports.parsing.listDocuments.mockReturnValue(listing.promise)
    ports.parsing.getContent.mockReturnValue(response.promise)
    const file = libraryFile({ markdownContent: '', originalMarkdownContent: '' })
    const view = mount({ loaded: true, library: [file] })
    act(() => view.current().page.setActiveLibraryFileId(file.id))
    await settle()
    expect(ports.parsing.getContent).toHaveBeenCalled()

    act(() => view.current().setLibraryLoaded(false))
    await act(async () => {
      response.resolve(content())
      listing.resolve({ items: [], total: 0 })
    })
    await settle()

    expect(ports.update).not.toHaveBeenCalled()
    expect(view.current().libraryFiles).toEqual([file])
  })
})

describe('shared parsing helper contracts', () => {
  it.each([
    [undefined, 1],
    [null, 1],
    ['', 1],
    [false, 1],
    [0, 0],
    ['3.5', 3.5],
  ])('preserves duration semantics for passive knowledge content: %j', async (duration, expectedDuration) => {
    ports.documents.list.mockResolvedValue({ total: 1, items: [remoteDocument('library-a')] })
    ports.documents.getParsedContent.mockResolvedValue({
      available: true,
      markdown_content: '# Passive knowledge',
      original_markdown_content: '# Passive knowledge',
      persisted_meta: { parse_duration_sec: duration },
    })
    const view = mount({ loaded: true, library: [libraryFile({ source: 'knowledge_base', durationSec: 1 })] })
    act(() => view.current().page.setActiveLibraryFileId('library-a'))
    await settle()

    expect(ports.update).toHaveBeenCalled()
    expect(view.current().libraryFiles[0]).toMatchObject({
      markdownContent: '# Passive knowledge',
      durationSec: expectedDuration,
    })
  })

  it.each([
    [undefined, undefined],
    [null, undefined],
    [0, 0],
    [3.5, 3.5],
  ])('preserves duration semantics for passive parsing content: %j', async (duration, expectedDuration) => {
    ports.parsing.listDocuments.mockResolvedValue({ total: 1, items: [remoteDocument('library-a')] })
    ports.parsing.getContent.mockResolvedValue(
      content({
        markdown_content: '# Passive parsing',
        original_markdown_content: '# Passive parsing',
        parse_duration_sec: duration,
      }),
    )
    const view = mount({ loaded: true, library: [libraryFile({ durationSec: 1 })] })
    act(() => view.current().page.setActiveLibraryFileId('library-a'))
    await settle()

    expect(ports.update).toHaveBeenCalled()
    expect(view.current().libraryFiles[0]).toMatchObject({
      markdownContent: '# Passive parsing',
      durationSec: expectedDuration,
    })
  })

  it.each(['parsing_workspace', 'knowledge_base'] as const)(
    'keeps saved quality available in the directory and after restoring its source: %s',
    async (source) => {
      const quality = { grade: 'pass' as const, reasons: [], evidence: { image_ocr: { error: 'image_unavailable' } } }
      const pdfQuality = {
        score: 0.8,
        text_quality_score: 0.8,
        format_consistency_score: 0.8,
        table_quality_score: 0.8,
        reading_order_score: null,
        page_count: 1,
        is_scanned: false,
      }
      const document = remoteDocument('library-a')
      if (source === 'parsing_workspace') {
        ports.parsing.listDocuments.mockResolvedValue({ total: 1, items: [document] })
        ports.parsing.getContent.mockResolvedValue(
          content({
            markdown_content: 'Saved quality body',
            original_markdown_content: 'Saved quality body',
            quality_gate: quality,
            pdf_quality: pdfQuality,
          }),
        )
      } else {
        ports.documents.list.mockResolvedValue({ total: 1, items: [document] })
        ports.documents.getParsedContent.mockResolvedValue({
          available: true,
          markdown_content: 'Saved quality body',
          original_markdown_content: 'Saved quality body',
          persisted_meta: { quality_gate: quality, pdf_quality: pdfQuality },
        })
      }
      const view = mount({ loaded: true, library: [libraryFile({ filename: 'saved.md', fileType: 'md', source })] })
      act(() => view.current().page.setActiveLibraryFileId('library-a'))
      await settle()
      expect(view.current().view.activeMarkdown).toBe('Saved quality body')
      expect(view.current().view.activeQualityGate).toEqual(quality)
      expect(view.current().view.activePdfQuality).toEqual(pdfQuality)
      await act(async () => {
        await view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file)
      })
      expect(view.current().view.activeQualityGate).toEqual(quality)
      expect(view.current().view.activePdfQuality).toEqual(pdfQuality)
    },
  )

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
    await settle()
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
      stats: { headingCount: 2, pageCount: 4, tableCount: 3, imageCount: 2, blockCount: 0 },
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
    ports.parsing.upload.mockResolvedValue(
      remoteDocument('created-a', {
        status: 'processing',
        metadata: { target_dataset_id: 'dataset-a', target_dataset_name: 'Dataset A' },
      }),
    )
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

  it.each([
    { suggested_backends: 'marker' },
    { pdf_sample: { samples: [{ page: 1, text_chars: 0, excerpt: 42 }] } },
    { pdf_sample: { samples: 'unreadable samples' } },
  ])('retains the primary parsing error when optional diagnostics have an invalid shape: %j', async (diagnostics) => {
    ports.parsing.parse.mockRejectedValue({
      response: { data: { detail: { message: 'Parser unavailable', diagnostics } } },
    })
    const view = mount({ files: [queuedFile()], library: [libraryFile()] })
    await act(async () => {
      await view.current().run.parseFile('queue-a')
    })
    expect(view.current().files[0]).toMatchObject({
      status: 'error',
      error: expect.stringContaining('Parser unavailable'),
    })
    expect(view.current().files[0].parseDiagnostics).toBeUndefined()
    expect(view.current().page.parseControllersRef.current.size).toBe(0)
  })

  it('preserves valid nullable error type and zero PDF diagnostic counts', async () => {
    const diagnostics = {
      error_type: null,
      suggested_backends: ['marker'],
      pdf_sample: { page_count: 0, is_scanned: false, samples: [{ page: 1, text_chars: 0, excerpt: '' }] },
    }
    ports.parsing.parse.mockRejectedValue({
      response: { data: { detail: { message: 'Parser unavailable', diagnostics } } },
    })
    const view = mount({ files: [queuedFile()], library: [libraryFile()] })
    await act(async () => {
      await view.current().run.parseFile('queue-a')
    })
    expect(view.current().files[0].parseDiagnostics).toEqual(diagnostics)
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

  it('retains the saved body, run and original File when a concurrent parse returns 409', async () => {
    ports.parsing.parse.mockRejectedValue({
      response: { status: 409, data: { detail: 'Document parsing is already in progress' } },
    })
    const run = {
      id: 'saved',
      parserBackend: 'text',
      parserLabel: 'Text',
      rawMarkdown: 'Saved original',
      cleanedMarkdown: 'Saved body',
      blocks: [],
      createdAt: 1,
    }
    const file = queuedFile({ status: 'parsed', markdownContent: 'Saved body', runs: [run], activeRunId: 'saved' })
    const view = mount({
      files: [file],
      library: [libraryFile({ markdownContent: 'Saved body', originalMarkdownContent: 'Saved original' })],
    })
    await act(async () => {
      await view.current().run.parseFile(file.id)
    })
    expect(view.current().files[0]).toMatchObject({
      markdownContent: 'Saved body',
      runs: [run],
      activeRunId: 'saved',
      error: expect.stringContaining('already in progress'),
    })
    expect(view.current().files[0].file).toBe(file.file)
    expect(view.current().page.parseControllersRef.current.size).toBe(0)
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
    await settle()
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

  it('selects the new run when two results complete within the same clock tick', async () => {
    ports.parsing.parse
      .mockResolvedValueOnce(content({ markdown_content: 'Version 1' }))
      .mockResolvedValueOnce(content({ markdown_content: 'Version 2' }))
    const view = mount({ files: [queuedFile()], library: [libraryFile()] })
    await act(async () => {
      await view.current().run.parseFile('queue-a')
    })
    await act(async () => {
      await view.current().run.parseFile('queue-a')
    })
    expect(view.current().view.activeMarkdown).toBe('Version 2')
    expect(new Set(view.current().files[0].runs?.map((run) => run.id)).size).toBe(2)
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
      content({ markdown_content: edited, original_markdown_content: '# Original' }),
    )
    const view = mount({ files: [file], library: [libraryFile()] })
    act(() => view.current().editor.handleStartEdit())
    act(() => view.current().page.setEditedContent(edited))
    await act(async () => {
      await view.current().editor.handleSaveEdit()
    })
    expect(ports.parsing.updateContent).toHaveBeenCalledWith('library-a', {
      markdown_content: edited,
      original_markdown_content: '# Original',
      parser_backend: 'auto',
      parse_duration_sec: null,
    })
    expect(view.current().files[0]).toMatchObject({
      governanceStatus: 'ready',
      markdownContent: edited,
      stats: { charCount: edited.length, lineCount: 4, headingCount: 2, blockCount: 0, pageCount: undefined },
    })
    expect(view.current().files[0].runs![0]).toEqual(file.runs![0])
    expect(view.current().files[0].runs![1]).toMatchObject({
      rawMarkdown: '# Original',
      cleanedMarkdown: edited,
      blocks: [],
    })
    expect(view.current().page.isEditing).toBe(false)
    expect(view.current().page.editSession).toBeNull()
    expect(view.current().page.rightPanelMode).toBe('markdown')
    expect(ports.update).toHaveBeenCalledWith(
      'library-a',
      expect.objectContaining({
        markdownContent: edited,
        originalMarkdownContent: '# Original',
        governanceStatus: 'ready',
        status: 'parsed',
      }),
    )
  })

  it('restores knowledge content with consistent parser metadata, validated elements and heading statistics', async () => {
    const element = { id: 'element-a', kind: 'paragraph', page: 1, text: 'remote' }
    ports.documents.getParsedContent.mockResolvedValue({
      available: true,
      markdown_content: '  # Remote\n## Second  ',
      original_markdown_content: '# Remote\n## Second',
      persisted_meta: {
        parser_backend: ' marker ',
        parse_duration_sec: '3.5',
        elements: [element],
      },
    })
    const view = mount({
      library: [
        libraryFile({ source: 'knowledge_base', datasetId: 'dataset-a', datasetName: 'Dataset A', durationSec: 1 }),
      ],
    })
    await act(async () => {
      await view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file, { forceRefresh: true })
    })
    expect(ports.documents.getParsedContent).toHaveBeenCalledWith(
      'library-a',
      { max_chars: 2_000_000 },
      { signal: expect.any(AbortSignal) },
    )
    expect(ports.update).toHaveBeenCalledWith(
      'library-a',
      expect.objectContaining({ parserBackend: 'marker', durationSec: 3.5, elements: [element] }),
    )
    expect(view.current().files[0]).toMatchObject({
      status: 'parsed',
      markdownContent: '  # Remote\n## Second  ',
      librarySource: 'knowledge_base',
      datasetId: 'dataset-a',
      elements: [element],
      stats: { headingCount: 2 },
      parserBackend: 'marker',
      parserLabel: getParserLabel('marker'),
      duration: 3.5,
      runs: [expect.objectContaining({ parserBackend: 'marker', parserLabel: getParserLabel('marker') })],
    })
    expect(view.current().page.autoParseFileId).toBeNull()
  })

  it('restores the parsing response backend and a valid zero duration into the queue and run', async () => {
    ports.parsing.getContent.mockResolvedValue(content({ parser_backend: 'marker', parse_duration_sec: 0 }))
    const view = mount({ library: [libraryFile({ durationSec: 5 })] })

    await act(async () => {
      await view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file, { forceRefresh: true })
    })

    expect(ports.update).toHaveBeenCalledWith('library-a', expect.objectContaining({ durationSec: 0 }))
    expect(view.current().files[0]).toMatchObject({
      parserBackend: 'marker',
      parserLabel: getParserLabel('marker'),
      duration: 0,
      runs: [expect.objectContaining({ parserBackend: 'marker', parserLabel: getParserLabel('marker') })],
    })
  })

  it.each([null, '', false])('does not turn invalid metadata duration %j into zero', async (duration) => {
    ports.documents.getParsedContent.mockResolvedValue({
      available: true,
      markdown_content: '# Remote',
      original_markdown_content: '# Remote',
      persisted_meta: { parse_duration_sec: duration },
    })
    const view = mount({ library: [libraryFile({ source: 'knowledge_base', durationSec: 1 })] })

    await act(async () => {
      await view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file, { forceRefresh: true })
    })

    expect(ports.update).toHaveBeenCalledWith('library-a', expect.objectContaining({ durationSec: 1 }))
    expect(view.current().files[0].duration).toBe(1)
  })

  it('filters the visible dataset without replacing the shared catalog and preserves status/duplicate policy', async () => {
    const element = { id: 'element-a', kind: 'paragraph', page: 1, text: 'mapped' }
    ports.parsing.listDocuments.mockResolvedValue({
      total: 1,
      items: [
        remoteDocument('parsing-a', {
          filename: 'report.pdf',
          status: 'processing',
          metadata: { target_dataset_id: ' dataset-a ', parser_backend: ' marker ', elements: [element] },
        }),
      ],
    })
    ports.documents.list.mockResolvedValue({
      total: 3,
      items: [
        remoteDocument('duplicate', { metadata: { workspace: 'parsing' } }),
        remoteDocument('knowledge-a', {
          filename: 'knowledge.pdf',
          status: 'failed',
          dataset_id: 'dataset-a',
          error_message: 'knowledge failed',
          metadata: { source_path: 'folder/knowledge.pdf' },
        }),
        remoteDocument('knowledge-b', { dataset_id: 'dataset-b' }),
      ],
    })
    const view = mount({ loaded: true })
    act(() => view.current().page.setSelectedDatasetId('dataset-a'))
    await settle()
    expect(ports.parsing.listDocuments).toHaveBeenCalledWith({ skip: 0, limit: 200 }, expect.anything())
    expect(ports.documents.list).toHaveBeenCalledWith({ skip: 0, limit: 200 }, expect.anything())
    expect(view.current().libraryFiles).toHaveLength(3)
    expect(
      view
        .current()
        .view.visibleLibraryOnlyFiles.map((file) => file.id)
        .sort(),
    ).toEqual(['knowledge-a', 'parsing-a'])
    act(() => view.current().page.setSelectedDatasetId('dataset-b'))
    await settle()
    expect(view.current().libraryFiles).toHaveLength(3)
    expect(view.current().view.visibleLibraryOnlyFiles.map((file) => file.id)).toEqual(['knowledge-b'])
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
  })
})

describe('library source availability and retry', () => {
  it('exposes a source cache check failure and recovers through the same retry', async () => {
    const failure = new Error('Source cache is unavailable')
    ports.cache.getDocSourceFromCache.mockRejectedValue(failure)
    const view = mount({ library: [libraryFile({ source: undefined, markdownContent: 'Known body' })], loaded: true })
    act(() => view.current().page.setActiveLibraryFileId('library-a'))
    await settle()
    expect(view.current().sourceStatus).toBe('unknown')
    expect(view.current().view.activeLibrarySourceError).toBe(failure)
    expect(view.current().view.activeMarkdown).toBe('Known body')
    ports.cache.getDocSourceFromCache.mockResolvedValue(null)
    act(() => view.current().view.retryLibrarySource())
    await settle()
    expect(view.current().sourceStatus).toBe('missing')
    expect(view.current().view.activeLibrarySourceError).toBeNull()
  })

  it('does not let an older source probe replace a successful local association', async () => {
    const probe = deferred<null>()
    ports.cache.getDocSourceFromCache.mockReturnValue(probe.promise)
    const view = mount({ library: [libraryFile({ source: undefined, markdownContent: 'Known body' })], loaded: true })
    act(() => view.current().page.setActiveLibraryFileId('library-a'))
    await settle()
    const input = document.createElement('input')
    Object.defineProperty(input, 'files', { value: [new File(['Source'], 'new-source.md')] })
    view.current().page.rebindTargetRef.current = { libraryId: 'library-a', autoParse: false }
    await act(async () => {
      await view.current().library.handleRebindFileSelect({ target: input } as React.ChangeEvent<HTMLInputElement>)
    })
    await act(async () => {
      probe.resolve(null)
    })
    expect(view.client.getQueryData(['parsing', 'library-source', 'library-a'])).toBe('available')
    expect(view.current().files[0].file.name).toBe('new-source.md')
  })

  it('selects a local library document needing a source without claiming parsing started', async () => {
    const view = mount({ library: [libraryFile({ source: undefined, status: 'pending' })] })
    await act(async () => {
      await view.current().run.parseFile('library-a')
    })
    await settle()
    expect(view.current().page.activeLibraryFileId).toBe('library-a')
    expect(view.current().sourceStatus).toBe('missing')
    expect(view.current().files).toEqual([])
    expect(ports.parsing.parse).not.toHaveBeenCalled()
    expect(ports.toast.success).not.toHaveBeenCalled()
  })

  it('keeps current session content when the cache still holds an older saved version', async () => {
    ports.cache.getDocContentFromCache.mockResolvedValue({
      id: 'library-a',
      markdownContent: 'Older cache',
      originalMarkdownContent: 'Older raw',
      updatedAt: 0,
    })
    const view = mount({
      library: [
        libraryFile({
          filename: 'report.md',
          fileType: 'md',
          markdownContent: 'Current session edit',
          originalMarkdownContent: '',
        }),
      ],
    })
    await act(async () => {
      await view.current().library.mountLibraryFileToQueue('library-a', new File(['Source'], 'report.md'))
    })
    expect(view.current().files[0]).toMatchObject({
      markdownContent: 'Current session edit',
      runs: [expect.objectContaining({ rawMarkdown: '' })],
    })
  })

  it('starts an inline retry even when selection hydrates saved content during the source wait', async () => {
    const source = deferred<null>()
    ports.cache.getDocSourceFromCache.mockReturnValue(source.promise)
    ports.cache.getDocContentFromCache.mockResolvedValue({
      id: 'library-a',
      markdownContent: 'Saved body',
      originalMarkdownContent: 'Saved raw',
      updatedAt: 0,
    })
    ports.parsing.listDocuments.mockResolvedValue({
      total: 1,
      items: [remoteDocument('library-a', { status: 'failed' })],
    })
    ports.documents.download.mockResolvedValue(new Blob(['Source']))
    ports.parsing.parse.mockResolvedValue(content())
    const view = mount({ library: [libraryFile({ status: 'error' })], loaded: true })
    let request!: Promise<void>
    act(() => {
      request = view.current().run.parseFile('library-a')
    })
    await settle()
    expect(view.current().libraryFiles[0].markdownContent).toBe('Saved body')
    await act(async () => {
      source.resolve(null)
      await request
    })
    await settle()
    expect(ports.parsing.parse).toHaveBeenCalledWith('library-a', expect.anything())
    expect(view.current().files[0].status).toBe('parsed')
  })

  it('checks a local preview source before offering a restore action', async () => {
    ports.cache.getDocSourceFromCache.mockResolvedValue(null)
    const view = mount({ library: [libraryFile({ source: undefined })], loaded: true })
    act(() => view.current().page.setActiveLibraryFileId('library-a'))
    await settle()
    expect(view.current().sourceStatus).toBe('missing')
  })

  it('restores a library-only document before starting its inline retry', async () => {
    ports.documents.download.mockResolvedValue(new Blob(['Source']))
    ports.parsing.parse.mockResolvedValue(content())
    const view = mount({ library: [libraryFile({ status: 'pending' })] })
    await act(async () => {
      await view.current().run.parseFile('library-a')
    })
    await settle()
    expect(ports.documents.download).toHaveBeenCalledWith(
      'library-a',
      { inline: true },
      { signal: expect.any(AbortSignal) },
    )
    expect(ports.parsing.parse).toHaveBeenCalledWith('library-a', expect.anything())
    expect(view.current().files[0]).toMatchObject({ libraryId: 'library-a', status: 'parsed' })
  })
})

describe('source restoration contracts', () => {
  it('stops an awaited reassociation quietly when its document was deleted', async () => {
    const pending = deferred<void>()
    ports.cache.saveDocSourceToCache.mockReturnValue(pending.promise)
    const view = mount({ library: [libraryFile({ source: undefined })] })
    const input = document.createElement('input')
    Object.defineProperty(input, 'files', { value: [new File(['Source'], 'selected.md')] })
    view.current().page.rebindTargetRef.current = { libraryId: 'library-a', autoParse: false }
    let request!: Promise<void>
    act(() => {
      request = view.current().library.handleRebindFileSelect({ target: input } as React.ChangeEvent<HTMLInputElement>)
    })
    await act(async () => {
      await view.current().queue.removeFile('library-a')
    })
    await act(async () => {
      pending.resolve()
      await request
    })
    expect(view.current().libraryFiles).toEqual([])
    expect(view.current().files).toEqual([])
    expect(ports.toast.error).not.toHaveBeenCalled()
    expect(ports.toast.warning).not.toHaveBeenCalled()
  })

  it('keeps the selected logical document open when its source arrives in the queue', async () => {
    const pending = deferred<{
      id: string
      filename: string
      mimeType: string
      size: number
      lastModified: number
      updatedAt: number
      blob: Blob
    }>()
    ports.cache.getDocSourceFromCache.mockReturnValue(pending.promise)
    ports.cache.getDocContentFromCache.mockResolvedValue({
      id: 'library-a',
      markdownContent: 'Saved body',
      originalMarkdownContent: 'Saved raw',
      updatedAt: 0,
    })
    const view = mount({
      library: [libraryFile({ source: undefined, status: 'error', error: 'Parser failed' })],
      loaded: true,
    })
    act(() => view.current().page.setActiveLibraryFileId('library-a'))
    await settle()
    await act(async () => {
      pending.resolve({
        id: 'library-a',
        filename: 'report.md',
        mimeType: 'text/markdown',
        size: 6,
        lastModified: 0,
        updatedAt: 0,
        blob: new Blob(['Source']),
      })
    })
    await settle()
    expect(view.current().view.activeFile?.libraryId).toBe('library-a')
    expect(view.current().page.activeLibraryFileId).toBeNull()
    expect(view.current().files).toHaveLength(1)
  })

  it.each([
    { markdownContent: 'User edit', originalMarkdownContent: 'Saved raw' },
    { markdownContent: 'Saved body', originalMarkdownContent: 'Different original' },
    { markdownContent: '', originalMarkdownContent: 'Saved raw' },
  ])('does not overwrite a newer library edit while restoring saved content: %j', async (edit) => {
    const pending = deferred<{
      id: string
      markdownContent: string
      originalMarkdownContent: string
      updatedAt: number
    }>()
    ports.cache.getDocContentFromCache.mockReturnValue(pending.promise)
    const original = libraryFile({ status: 'error' })
    const view = mount({ library: [original] })
    let request!: Promise<string | null>
    act(() => {
      request = view.current().library.mountLibraryFileToQueue(original.id, queuedFile().file)
    })
    await settle()
    act(() => view.current().setLibraryFiles([{ ...original, ...edit }]))
    await act(async () => {
      pending.resolve({
        id: original.id,
        markdownContent: 'Saved body',
        originalMarkdownContent: 'Saved raw',
        updatedAt: 0,
      })
      await request
    })
    expect(view.current().files).toEqual([])
    expect(view.current().libraryFiles[0]).toMatchObject(edit)
    expect(ports.update).not.toHaveBeenCalled()
  })

  it('accepts identical saved content hydrated by the library while its source is being restored', async () => {
    const pending = deferred<{
      id: string
      markdownContent: string
      originalMarkdownContent: string
      updatedAt: number
    }>()
    ports.cache.getDocContentFromCache.mockReturnValue(pending.promise)
    const original = libraryFile({ status: 'error', error: 'Parser failed' })
    const view = mount({ library: [original] })
    let request!: Promise<string | null>
    act(() => {
      request = view.current().library.mountLibraryFileToQueue(original.id, queuedFile().file)
    })
    await settle()
    act(() =>
      view
        .current()
        .setLibraryFiles([{ ...original, markdownContent: 'Saved body', originalMarkdownContent: 'Saved raw' }]),
    )
    await act(async () => {
      pending.resolve({
        id: original.id,
        markdownContent: 'Saved body',
        originalMarkdownContent: 'Saved raw',
        updatedAt: 0,
      })
      await request
    })
    expect(view.current().files[0]).toMatchObject({
      status: 'error',
      markdownContent: 'Saved body',
      runs: [expect.objectContaining({ rawMarkdown: 'Saved raw' })],
    })
  })

  it.each(['error', 'pending', 'parsing'] as const)(
    'restores saved workspace content while preserving %s task feedback',
    async (status) => {
      const original = libraryFile({
        status,
        markdownContent: 'Saved user draft',
        originalMarkdownContent: 'Original source',
        error: status === 'error' ? 'Parser failed' : undefined,
      })
      const view = mount({ library: [original] })
      await act(async () => {
        await view.current().library.mountLibraryFileToQueue(original.id, queuedFile().file)
      })
      expect(view.current().files[0]).toMatchObject({
        status: status === 'parsing' ? 'error' : status,
        markdownContent: 'Saved user draft',
        runs: [expect.objectContaining({ rawMarkdown: 'Original source', cleanedMarkdown: 'Saved user draft' })],
      })
      if (status === 'error') expect(view.current().files[0].error).toBe('Parser failed')
      if (status === 'parsing') expect(view.current().files[0].error).toContain('中断')
    },
  )

  it('keeps the newest source when two restorations of one document complete out of order', async () => {
    const first = deferred<ParsingContentResponse>()
    const second = deferred<ParsingContentResponse>()
    ports.parsing.getContent.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const view = mount({ library: [libraryFile()] })
    const older = new File(['Old source'], 'older.pdf')
    const newer = new File(['New source'], 'newer.pdf')
    let firstRequest!: Promise<string | null>
    let secondRequest!: Promise<string | null>
    await act(async () => {
      firstRequest = view.current().library.mountLibraryFileToQueue('library-a', older)
    })
    expect(ports.parsing.getContent).toHaveBeenCalledTimes(1)
    const firstSignal = ports.parsing.getContent.mock.calls[0][1].signal as AbortSignal
    const firstAborted = expect(firstRequest).rejects.toMatchObject({ name: 'AbortError' })
    await act(async () => {
      secondRequest = view.current().library.mountLibraryFileToQueue('library-a', newer)
    })
    expect(firstSignal.aborted).toBe(true)
    expect(ports.parsing.getContent).toHaveBeenCalledTimes(2)
    await act(async () => {
      second.resolve(content())
      await secondRequest
    })
    await act(async () => {
      first.resolve(content())
      await firstAborted
    })
    expect(view.current().files).toHaveLength(1)
    expect(view.current().files[0].file).toBe(newer)
  })

  it.each(['scope', 'session', 'unmount'])(
    'does not continue rebinding after %s invalidates the cache wait',
    async (change) => {
      const pending = deferred<void>()
      ports.cache.saveDocSourceToCache.mockReturnValue(pending.promise)
      const original = libraryFile()
      const view = mount({ library: [original] })
      const input = document.createElement('input')
      Object.defineProperty(input, 'files', { value: [new File(['Source'], 'selected.md')] })
      view.current().page.rebindTargetRef.current = { libraryId: original.id, autoParse: true }
      let request!: Promise<void>
      act(() => {
        request = view
          .current()
          .library.handleRebindFileSelect({ target: input } as React.ChangeEvent<HTMLInputElement>)
      })
      if (change === 'scope') ports.authScope = 'next-scope'
      if (change === 'session') ports.authRevision += 1
      if (change === 'unmount') view.unmount()
      await act(async () => {
        pending.resolve()
        await request
      })
      expect(ports.update).not.toHaveBeenCalled()
      expect(ports.parsing.parse).not.toHaveBeenCalled()
      expect(ports.toast.warning).not.toHaveBeenCalled()
    },
  )

  it('does not rewrite remote source metadata while mounting a local file for reparse', async () => {
    const pending = deferred<ParsingContentResponse>()
    ports.parsing.parse.mockReturnValue(pending.promise)
    const original = libraryFile({ filename: 'server.pdf', fileSize: 91 })
    const view = mount({ library: [original] })
    await act(async () => {
      await view
        .current()
        .library.mountLibraryFileToQueue(original.id, new File(['Local source'], 'local.md'), { autoParse: true })
    })
    expect(view.current().libraryFiles[0]).toMatchObject({ filename: 'server.pdf', fileSize: 91, fileType: 'pdf' })
    expect(view.current().files[0]).toMatchObject({ name: 'server.pdf', parserBackend: 'auto' })
    await act(async () => {
      pending.resolve(content())
    })
  })

  it('uses the current library folder when restoring content finishes after a move', async () => {
    const pending = deferred<void>()
    ports.update.mockImplementation((_id: string, updates: Partial<ParsedFileData>) =>
      'markdownContent' in updates ? pending.promise : Promise.resolve(),
    )
    const view = mount({ library: [libraryFile()] })
    let request!: Promise<string | null>
    act(() => {
      request = view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file)
    })
    await settle()
    await act(async () => {
      await view.current().queue.moveFileToFolder('library-a', 'moved-folder')
    })
    await act(async () => {
      pending.resolve()
      await request
    })
    expect(view.current().files[0].folderId).toBe('moved-folder')
    expect(view.current().libraryFiles[0].folderId).toBe('moved-folder')
  })

  it('restores every cached pending source in the selected folder', async () => {
    const first = libraryFile({ source: undefined, status: 'pending' })
    const second = libraryFile({ id: 'library-b', source: undefined, status: 'pending' })
    ports.cache.getDocSourceFromCache.mockImplementation(async (id: string) => ({
      id,
      filename: `${id}.md`,
      mimeType: 'text/markdown',
      size: 0,
      lastModified: 0,
      updatedAt: 0,
      blob: new Blob(['Source']),
    }))
    const view = mount({ library: [first, second], loaded: true, strict: true })
    await settle()
    await settle()
    expect(
      view
        .current()
        .files.map((file) => file.libraryId)
        .sort(),
    ).toEqual(['library-a', 'library-b'])
    expect(view.current().page.isQueueRehydrating).toBe(false)
  })

  it.each(['completed', 'pending'] as const)(
    'keeps a newer association when an automatic source read finishes while the association is %s',
    async (associationState) => {
      const sourceRead = deferred<Awaited<ReturnType<typeof ports.cache.getDocSourceFromCache>>>()
      const sourceWrite = deferred<void>()
      ports.cache.getDocSourceFromCache.mockReturnValue(sourceRead.promise)
      ports.cache.saveDocSourceToCache.mockReturnValue(sourceWrite.promise)
      const view = mount({ library: [libraryFile({ source: undefined, status: 'pending' })], loaded: true })
      await settle()
      const selectedFile = new File(['New source'], 'new-source.md')
      const input = document.createElement('input')
      Object.defineProperty(input, 'files', { value: [selectedFile] })
      view.current().page.rebindTargetRef.current = { libraryId: 'library-a', autoParse: false }
      let association!: Promise<void>
      act(() => {
        association = view
          .current()
          .library.handleRebindFileSelect({ target: input } as React.ChangeEvent<HTMLInputElement>)
      })
      if (associationState === 'completed') {
        await act(async () => {
          sourceWrite.resolve()
          await association
        })
      }
      await act(async () => {
        sourceRead.resolve({
          id: 'library-a',
          filename: 'old-source.md',
          mimeType: 'text/markdown',
          size: 10,
          lastModified: 0,
          updatedAt: 0,
          blob: new Blob(['Old source']),
        })
      })
      if (associationState === 'pending') {
        await act(async () => {
          sourceWrite.resolve()
          await association
        })
      }
      await settle()
      expect(view.current().files).toHaveLength(1)
      expect(view.current().files[0].file).toBe(selectedFile)
      expect(ports.toast.error).not.toHaveBeenCalled()
    },
  )

  it('reports an automatic source read failure instead of calling it a missing source', async () => {
    ports.cache.getDocSourceFromCache.mockRejectedValue(new Error('Source cache read denied'))
    const view = mount({ library: [libraryFile({ source: undefined, status: 'pending' })], loaded: true })
    await settle()
    expect(ports.toast.error).toHaveBeenCalledWith(expect.stringContaining('Source cache read denied'))
    expect(ports.toast.warning).not.toHaveBeenCalled()
    expect(view.current().files).toEqual([])
    expect(view.current().page.isQueueRehydrating).toBe(false)
  })
})

describe('parsing content restoration', () => {
  it('keeps a completed empty parsing result when an older cache still contains text', async () => {
    ports.cache.getDocContentFromCache.mockResolvedValue({
      id: 'library-a',
      markdownContent: 'Older cached body',
      originalMarkdownContent: 'Older raw',
      updatedAt: 0,
    })
    ports.parsing.parse.mockResolvedValue(content({ markdown_content: '', original_markdown_content: '' }))
    const view = mount({ files: [queuedFile()], library: [libraryFile()] })
    await act(async () => {
      await view.current().run.parseFile('queue-a')
    })
    await act(async () => {
      await view.current().library.mountLibraryFileToQueue('library-a', new File(['Source'], 'report.md'))
    })
    expect(view.current().libraryFiles[0]).toMatchObject({ markdownContent: '', originalMarkdownContent: '' })
    expect(view.current().files[0].markdownContent).toBe('')
    expect(ports.cache.getDocContentFromCache).not.toHaveBeenCalled()
  })

  it.each(['', '    const value = 1\n\n'])(
    'preserves cached processed text %j instead of restoring source text',
    async (markdown) => {
      ports.cache.getDocContentFromCache.mockResolvedValue({
        id: 'library-a',
        markdownContent: markdown,
        originalMarkdownContent: 'Original text@@1 0 10 0 10##',
        updatedAt: 1,
      })
      const view = mount({ library: [libraryFile({ filename: 'report.md', fileType: 'md' })] })

      await act(async () => {
        await view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file)
      })

      expect(view.current().files[0]).toMatchObject({
        status: 'parsed',
        markdownContent: markdown,
        runs: [expect.objectContaining({ cleanedMarkdown: markdown, rawMarkdown: 'Original text@@1 0 10 0 10##' })],
      })
      expect(view.current().view.activeMarkdown).toBe(markdown)
      expect(ports.parsing.getContent).not.toHaveBeenCalled()
    },
  )

  it('restores a known empty cached document as parsed', async () => {
    ports.cache.getDocContentFromCache.mockResolvedValue({
      id: 'library-a',
      markdownContent: '',
      originalMarkdownContent: '',
      updatedAt: 1,
    })
    const view = mount({ library: [libraryFile({ filename: 'empty.md', fileType: 'md' })] })

    await act(async () => {
      await view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file)
    })

    expect(view.current().files[0]).toMatchObject({
      status: 'parsed',
      markdownContent: '',
      runs: [expect.objectContaining({ blocks: [] })],
    })
    expect(ports.parsing.getContent).not.toHaveBeenCalled()
  })

  it('propagates a cache read error without replacing saved content from the server', async () => {
    const error = new Error('Saved content cannot be read')
    ports.cache.getDocContentFromCache.mockRejectedValue(error)
    const view = mount({ library: [libraryFile()] })

    await act(async () => {
      await expect(view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file)).rejects.toBe(error)
    })

    expect(view.current().files).toEqual([])
    expect(ports.update).not.toHaveBeenCalled()
    expect(ports.parsing.getContent).not.toHaveBeenCalled()
  })

  it('does not report unavailable knowledge content as an empty parsed document', async () => {
    ports.documents.getParsedContent.mockResolvedValue({
      available: false,
      markdown_content: '',
      original_markdown_content: '',
      persisted_meta: {},
    })
    const view = mount({ library: [libraryFile({ source: 'knowledge_base' })] })

    await act(async () => {
      await expect(view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file)).rejects.toThrow(
        '解析正文暂不可用',
      )
    })

    expect(view.current().files).toEqual([])
    expect(ports.update).not.toHaveBeenCalled()
  })

  it('uses the requested backend when persisted metadata contains a blank actual backend', async () => {
    ports.documents.getParsedContent.mockResolvedValue({
      available: true,
      markdown_content: 'Body',
      original_markdown_content: 'Source',
      persisted_meta: { parser_backend: '  ', parser_backend_requested: 'marker' },
    })
    const view = mount({ library: [libraryFile({ source: 'knowledge_base' })] })
    await act(async () => {
      await view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file)
    })
    expect(view.current().files[0].parserBackend).toBe('marker')
  })

  it('waits for a library update before publishing a restored queue item', async () => {
    const pending = deferred<void>()
    ports.update.mockReturnValue(pending.promise)
    const view = mount({ library: [libraryFile()] })
    let restored!: Promise<string | null>
    act(() => {
      restored = view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file)
    })
    await settle()

    expect(ports.update).toHaveBeenCalled()
    expect(view.current().files).toEqual([])
    await act(async () => {
      pending.resolve()
      await restored
    })
    expect(view.current().files[0].status).toBe('parsed')
  })

  it('discards a restoration if its library entry was removed during the read', async () => {
    const pending = deferred<null>()
    ports.cache.getDocContentFromCache.mockReturnValue(pending.promise)
    const view = mount({ library: [libraryFile()] })
    let restored!: Promise<string | null>
    act(() => {
      restored = view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file)
    })
    act(() => view.current().setLibraryFiles([]))
    await act(async () => {
      pending.resolve(null)
      await restored
    })

    expect(view.current().files).toEqual([])
    expect(ports.update).not.toHaveBeenCalled()
  })

  it('uses the selected run even when its processed body is empty', () => {
    const view = mount({
      files: [
        queuedFile({
          status: 'parsed',
          markdownContent: 'Another run',
          activeRunId: 'cleared',
          runs: [
            {
              id: 'cleared',
              parserBackend: 'auto',
              parserLabel: 'Auto',
              rawMarkdown: 'Original',
              cleanedMarkdown: '',
              blocks: [],
              createdAt: 1,
            },
          ],
        }),
      ],
    })

    expect(view.current().view.activeMarkdown).toBe('')
  })

  it('opens an editor for a known empty parsed body', () => {
    const view = mount({ files: [queuedFile({ status: 'parsed', markdownContent: '' })] })
    act(() => view.current().editor.handleStartEdit())

    expect(view.current().page.isEditing).toBe(true)
    expect(view.current().page.editedContent).toBe('')
  })

  it('keeps restored knowledge content read only in the parsing workspace', async () => {
    const view = mount({
      files: [queuedFile({ status: 'parsed', librarySource: 'knowledge_base', markdownContent: 'Knowledge body' })],
    })
    act(() => view.current().editor.handleStartEdit())
    await act(async () => {
      await view.current().editor.handleSaveEdit()
    })

    expect(view.current().page.isEditing).toBe(false)
    expect(ports.parsing.updateContent).not.toHaveBeenCalled()
  })

  it('keeps the new selection when an earlier source restoration finishes', async () => {
    const pending = deferred<null>()
    ports.cache.getDocContentFromCache.mockReturnValue(pending.promise)
    const view = mount({ library: [libraryFile(), libraryFile({ id: 'library-b' })] })
    act(() => view.current().page.setActiveLibraryFileId('library-a'))
    let request!: Promise<string | null>
    act(() => {
      request = view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file)
    })
    act(() => view.current().page.setActiveLibraryFileId('library-b'))
    await act(async () => {
      pending.resolve(null)
      await request
    })

    expect(view.current().page.activeLibraryFileId).toBe('library-b')
    expect(view.current().page.activeFileId).toBeNull()
    expect(view.current().files).toHaveLength(1)
  })

  it('rejects truncated knowledge content before it replaces the full saved body', async () => {
    ports.documents.getParsedContent.mockResolvedValue({
      available: true,
      markdown_content: 'Part',
      original_markdown_content: 'Part',
      markdown_truncated: true,
      original_markdown_truncated: false,
    })
    const view = mount({ library: [libraryFile({ source: 'knowledge_base' })] })
    await act(async () => {
      await expect(view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file)).rejects.toThrow(
        '解析正文超过读取范围',
      )
    })

    expect(ports.update).not.toHaveBeenCalled()
    expect(view.current().files).toEqual([])
  })

  it('shows a read failure and retries to a known empty result', async () => {
    const failure = new Error('Content service unavailable')
    ports.parsing.listDocuments.mockResolvedValue({ total: 1, items: [remoteDocument('library-a')] })
    ports.parsing.getContent.mockRejectedValue(failure)
    const view = mount({ loaded: true, library: [libraryFile({ filename: 'report.md', fileType: 'md' })] })
    act(() => view.current().page.setActiveLibraryFileId('library-a'))
    await settle()

    expect(view.current().view.activeLibraryContentError).toBe(failure)
    expect(view.current().view.hasLibraryContent).toBe(false)
    expect(ports.update).not.toHaveBeenCalled()

    ports.parsing.getContent.mockResolvedValue(content({ markdown_content: '', original_markdown_content: '' }))
    act(() => view.current().view.retryLibraryContent())
    await settle()

    expect(view.current().view.activeLibraryContentError).toBeNull()
    expect(view.current().view.hasLibraryContent).toBe(true)
    expect(view.current().view.activeMarkdown).toBe('')
    expect(view.current().libraryFiles[0].markdownContent).toBe('')
  })

  it('cancels the previous selection without publishing its delayed body', async () => {
    const pending = deferred<ParsingContentResponse>()
    let requestSignal!: AbortSignal
    ports.parsing.listDocuments.mockResolvedValue({
      total: 2,
      items: [remoteDocument('library-a'), remoteDocument('library-b')],
    })
    ports.parsing.getContent.mockImplementation((id: string, { signal }: { signal: AbortSignal }) => {
      if (id === 'library-a') {
        requestSignal = signal
        return pending.promise
      }
      return Promise.resolve(content({ document_id: id, markdown_content: 'Second body' }))
    })
    const view = mount({
      loaded: true,
      library: [libraryFile({ fileType: 'md' }), libraryFile({ id: 'library-b', fileType: 'md' })],
    })
    act(() => view.current().page.setActiveLibraryFileId('library-a'))
    await settle()
    expect(view.current().view.isLibraryContentLoading).toBe(true)
    act(() => view.current().page.setActiveLibraryFileId('library-b'))
    await settle()
    expect(requestSignal.aborted).toBe(true)

    await act(async () => pending.resolve(content({ markdown_content: 'Stale body' })))
    await settle()

    expect(view.current().view.activeMarkdown).toBe('Second body')
    expect(ports.update.mock.calls.some(([id]) => id === 'library-a')).toBe(false)
  })

  it('keeps the saved text and original when remote PDF positions belong to a different body', async () => {
    ports.cache.getDocContentFromCache.mockResolvedValue({
      id: 'library-a',
      markdownContent: '',
      originalMarkdownContent: 'Old source',
      updatedAt: 1,
    })
    ports.parsing.getContent.mockResolvedValue(
      content({ markdown_content: 'Server body', original_markdown_content: 'Source@@1 0 10 0 10##' }),
    )
    const view = mount({ library: [libraryFile()] })

    await act(async () => {
      await view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file)
    })

    expect(view.current().files[0]).toMatchObject({
      markdownContent: '',
      runs: [expect.objectContaining({ rawMarkdown: 'Old source', blocks: [] })],
    })
    expect(view.current().libraryFiles[0].markdownContent).toBe('')
  })

  it('polls pending knowledge content even when an earlier empty body is cached', async () => {
    ports.documents.list.mockResolvedValue({ total: 1, items: [remoteDocument('library-a', { status: 'processing' })] })
    ports.cache.getDocContentFromCache.mockResolvedValue({
      id: 'library-a',
      markdownContent: '',
      originalMarkdownContent: '',
      updatedAt: 1,
    })
    ports.documents.get.mockResolvedValue({ status: 'processing', error_message: null })
    ports.documents.getParsedContent.mockResolvedValue({ available: true, markdown_content: 'Original source text' })
    const view = mount({ loaded: true, library: [libraryFile({ source: 'knowledge_base', status: 'parsing' })] })
    act(() => view.current().page.setActiveLibraryFileId('library-a'))
    await settle()
    expect(view.current().view.hasLibraryContent).toBe(true)
    expect(view.current().libraryFiles[0].status).toBe('parsing')
    expect(view.current().view.activeLibraryContentError).toBeNull()
    expect(ports.documents.getParsedContent).not.toHaveBeenCalled()

    ports.documents.get.mockResolvedValue({ status: 'completed', error_message: null })
    ports.documents.getParsedContent.mockResolvedValue({
      available: true,
      markdown_content: 'Finished body',
      original_markdown_content: 'Finished source',
      persisted_meta: {},
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_100)
    })
    await settle()

    expect(ports.documents.get).toHaveBeenCalledTimes(2)
    expect(ports.documents.getParsedContent).toHaveBeenCalledWith(
      'library-a',
      { max_chars: 2_000_000 },
      { signal: expect.any(AbortSignal) },
    )
    expect(view.current().libraryFiles[0]).toMatchObject({ status: 'parsed', markdownContent: 'Finished body' })
    expect(view.current().view.hasLibraryContent).toBe(true)

    // The completed status opens its own cache entry after the final poll.
    expect(ports.documents.getParsedContent).toHaveBeenCalledTimes(2)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_000)
    })
    expect(ports.documents.get).toHaveBeenCalledTimes(2)
    expect(ports.documents.getParsedContent).toHaveBeenCalledTimes(2)
  })

  it('ends knowledge polling with the actual failed task and keeps its saved body', async () => {
    ports.documents.list.mockResolvedValue({ total: 1, items: [remoteDocument('library-a', { status: 'processing' })] })
    ports.documents.get.mockResolvedValue({ status: 'processing', error_message: null })
    ports.documents.getParsedContent.mockResolvedValue({ available: true, markdown_content: 'Previous body' })
    const view = mount({
      loaded: true,
      library: [libraryFile({ source: 'knowledge_base', status: 'parsing', markdownContent: 'Previous body' })],
    })
    act(() => view.current().page.setActiveLibraryFileId('library-a'))
    await settle()
    expect(view.current().libraryFiles[0].status).toBe('parsing')
    ports.documents.get.mockResolvedValue({ status: 'failed', error_message: 'Task failed' })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_100)
    })
    await settle()

    expect(view.current().libraryFiles[0]).toMatchObject({
      status: 'error',
      error: 'Task failed',
      markdownContent: 'Previous body',
    })
    expect(ports.documents.getParsedContent).not.toHaveBeenCalled()
    const requests = ports.documents.get.mock.calls.length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_100)
    })
    expect(ports.documents.get).toHaveBeenCalledTimes(requests)
  })

  it('keeps tracking a knowledge task after opening its original file', async () => {
    ports.documents.list.mockResolvedValue({ total: 1, items: [remoteDocument('library-a', { status: 'processing' })] })
    ports.documents.get.mockResolvedValue({ status: 'processing', error_message: null })
    const view = mount({ loaded: true, library: [libraryFile({ source: 'knowledge_base', status: 'parsing' })] })
    await settle()
    await act(async () => {
      await view.current().library.mountLibraryFileToQueue('library-a', queuedFile().file)
    })
    await settle()
    expect(view.current().view.activeFile?.status).toBe('parsing')
    expect(view.current().libraryFiles[0].status).toBe('parsing')
    expect(ports.update.mock.calls.some(([, update]) => update.error === '上次解析被中断，请重试')).toBe(false)

    ports.documents.get.mockResolvedValue({ status: 'completed', error_message: null })
    ports.documents.getParsedContent.mockResolvedValue({
      available: true,
      markdown_content: 'Finished body',
      original_markdown_content: 'Source@@1 0 10 0 10##',
      persisted_meta: {},
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_100)
    })
    await settle()

    expect(view.current().view.activeFile?.status).toBe('parsed')
    expect(view.current().view.visibleQueueFiles[0].status).toBe('parsed')
    expect(view.current().view.queueFiles[0].status).toBe('parsed')
    expect(view.current().view.activeMarkdown).toBe('Finished body')
    expect(view.current().view.activeBlocksWithPositions).toHaveLength(1)
  })

  it('preserves an empty parse response and unknown server duration', async () => {
    const pending = deferred<ParsingContentResponse>()
    ports.parsing.parse.mockReturnValue(pending.promise)
    const view = mount({ files: [queuedFile()], library: [libraryFile()] })
    let request!: Promise<void>
    act(() => {
      request = view.current().run.parseFile('queue-a')
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000)
    })
    await act(async () => {
      pending.resolve(
        content({ markdown_content: '', original_markdown_content: 'Original', parse_duration_sec: null }),
      )
      await request
    })

    expect(view.current().files[0]).toMatchObject({
      status: 'parsed',
      markdownContent: '',
      duration: undefined,
      runs: [expect.objectContaining({ rawMarkdown: 'Original', cleanedMarkdown: '' })],
    })
  })

  it('publishes the body acknowledged by the server when an edit becomes empty', async () => {
    ports.parsing.updateContent.mockResolvedValue(content({ markdown_content: '', original_markdown_content: '' }))
    const view = mount({
      files: [queuedFile({ status: 'parsed', markdownContent: 'Before' })],
      library: [libraryFile()],
    })
    act(() => view.current().editor.handleStartEdit())
    act(() => view.current().page.setEditedContent('Submitted text'))

    await act(async () => {
      await view.current().editor.handleSaveEdit()
    })

    expect(view.current().libraryFiles[0]).toMatchObject({ markdownContent: '', originalMarkdownContent: '' })
    expect(view.current().files[0].markdownContent).toBe('')
  })
})

describe('knowledge parsing request ownership', () => {
  it.each(['scope', 'session', 'unmount', 'removed'])(
    'does not continue a pipeline patch after %s invalidates it',
    async (change) => {
      const pending = deferred<void>()
      ports.documents.patchPipeline.mockReturnValue(pending.promise)
      const view = mount({ library: [libraryFile({ source: 'knowledge_base' })] })
      let request!: Promise<void>
      act(() => {
        request = view.current().run.startKnowledgeParsing('library-a', 'auto')
      })
      if (change === 'scope') ports.authScope = 'next-scope'
      if (change === 'session') ports.authRevision += 1
      if (change === 'unmount') view.unmount()
      if (change === 'removed') act(() => view.current().setLibraryFiles([]))
      await act(async () => {
        pending.resolve()
        await request
      })
      expect(ports.documents.retry).not.toHaveBeenCalled()
      expect(ports.update).not.toHaveBeenCalled()
      expect(ports.toast.success).not.toHaveBeenCalled()
    },
  )

  it('keeps the previous document status when the request was not accepted', async () => {
    const original = libraryFile({ source: 'knowledge_base', markdownContent: 'Keep body' })
    ports.documents.retry.mockRejectedValue(new Error('Queue denied'))
    const view = mount({ library: [original] })
    await act(async () => {
      await view.current().run.startKnowledgeParsing('library-a', 'auto')
    })
    expect(view.current().libraryFiles).toEqual([original])
    expect(ports.toast.error).toHaveBeenCalledWith(expect.stringContaining('Queue denied'))
    expect(ports.toast.success).not.toHaveBeenCalled()
  })

  it('distinguishes an accepted parsing request from a failed local status write', async () => {
    ports.update.mockRejectedValue(new Error('Index write denied'))
    const view = mount({ library: [libraryFile({ source: 'knowledge_base' })] })
    await act(async () => {
      await view.current().run.startKnowledgeParsing('library-a', 'auto')
    })
    expect(ports.documents.retry).toHaveBeenCalledTimes(1)
    expect(ports.toast.error).toHaveBeenCalledWith(expect.stringContaining('解析请求已提交'))
    expect(ports.toast.success).not.toHaveBeenCalled()
  })

  it('keeps independent knowledge documents in flight and cleans their request owners', async () => {
    const first = deferred<void>()
    const second = deferred<void>()
    ports.documents.patchPipeline.mockImplementation((id: string) =>
      id === 'library-a' ? first.promise : second.promise,
    )
    const view = mount({
      library: [libraryFile({ source: 'knowledge_base' }), libraryFile({ id: 'library-b', source: 'knowledge_base' })],
    })
    let requestA!: Promise<void>
    let requestB!: Promise<void>
    act(() => {
      requestA = view.current().run.startKnowledgeParsing('library-a', 'auto')
      requestB = view.current().run.startKnowledgeParsing('library-b', 'auto')
    })
    await act(async () => {
      second.resolve()
      await requestB
    })
    await act(async () => {
      first.resolve()
      await requestA
    })
    expect(ports.documents.retry.mock.calls.map(([id]) => id)).toEqual(['library-b', 'library-a'])
    expect(view.current().libraryFiles.every((file) => file.status === 'parsing')).toBe(true)
    expect(view.current().page.parseControllersRef.current.size).toBe(0)
  })
})

describe('parsing editor handoff and feedback', () => {
  it('hands off one saved library document without requiring its original binary or changing batch selection', async () => {
    const saved = libraryFile({
      source: undefined,
      markdownContent: 'Saved body',
      originalMarkdownContent: 'Saved original',
    })
    const view = mount({ library: [saved] })
    act(() => view.current().setSelectedGovernanceFileIds(new Set(['another-document'])))
    await act(async () => {
      await view.current().editor.handleSubmitToGovernance(saved)
    })
    expect(view.current().files).toHaveLength(0)
    expect(view.current().libraryFiles[0]).toMatchObject({
      markdownContent: 'Saved body',
      originalMarkdownContent: 'Saved original',
      governanceStatus: 'submitted',
    })
    expect(view.current().selectedGovernanceFileIds).toEqual(new Set(['another-document']))
    expect(ports.push).toHaveBeenCalledWith('/data-governance')
  })

  it('keeps the editor draft and saved body when an in-flight parse rejects saving with 409', async () => {
    ports.parsing.updateContent.mockRejectedValue({
      response: { status: 409, data: { detail: 'Finish document parsing before editing its content' } },
    })
    const view = mount({
      files: [queuedFile({ status: 'parsed', markdownContent: 'Saved body' })],
      library: [libraryFile({ markdownContent: 'Saved body', originalMarkdownContent: 'Saved original' })],
    })
    act(() => view.current().editor.handleStartEdit())
    act(() => view.current().page.setEditedContent('Draft kept on conflict'))
    await act(async () => {
      await view.current().editor.handleSaveEdit()
    })
    expect(view.current().page.isEditing).toBe(true)
    expect(view.current().page.editedContent).toBe('Draft kept on conflict')
    expect(view.current().files[0].markdownContent).toBe('Saved body')
    expect(ports.update).not.toHaveBeenCalled()
    expect(ports.toast.success).not.toHaveBeenCalled()
    expect(ports.toast.error).toHaveBeenCalledWith(expect.stringContaining('Finish document parsing'))
  })

  it('keeps the draft and distinguishes an acknowledged server save from a failed local update', async () => {
    ports.update.mockRejectedValue(new Error('Index write denied'))
    const view = mount({
      files: [queuedFile({ status: 'parsed', markdownContent: 'Before' })],
      library: [libraryFile()],
    })
    act(() => view.current().editor.handleStartEdit())
    act(() => view.current().page.setEditedContent('Confirmed by server'))
    await act(async () => {
      await view.current().editor.handleSaveEdit()
    })
    expect(ports.parsing.updateContent).toHaveBeenCalledWith('library-a', {
      markdown_content: 'Confirmed by server',
      original_markdown_content: '',
      parser_backend: 'auto',
      parse_duration_sec: null,
    })
    expect(view.current().page.isEditing).toBe(true)
    expect(view.current().page.editedContent).toBe('Confirmed by server')
    expect(ports.toast.error).toHaveBeenCalledWith(expect.stringContaining('正文已保存到服务器'))
    expect(ports.toast.success).not.toHaveBeenCalled()
  })

  it.each(['Original raw', '', '   '])(
    'preserves local original %j while saving the processed draft',
    async (original) => {
      const run = {
        id: 'run-a',
        parserBackend: 'text',
        parserLabel: 'Text',
        rawMarkdown: original,
        cleanedMarkdown: 'Before',
        blocks: [],
        createdAt: 0,
      }
      const view = mount({
        files: [
          queuedFile({
            librarySource: undefined,
            status: 'parsed',
            markdownContent: 'Before',
            runs: [run],
            activeRunId: run.id,
          }),
        ],
        library: [libraryFile({ source: undefined, originalMarkdownContent: original })],
      })
      act(() => view.current().editor.handleStartEdit())
      act(() => view.current().page.setEditedContent('New processed body'))
      await act(async () => {
        await view.current().editor.handleSaveEdit()
      })
      expect(view.current().libraryFiles[0]).toMatchObject({
        markdownContent: 'New processed body',
        originalMarkdownContent: original,
      })
      expect(view.current().files[0].runs?.[0]).toMatchObject({
        cleanedMarkdown: 'New processed body',
        rawMarkdown: original,
      })
    },
  )

  it('completes a handoff if only the next parser preference changed during the write', async () => {
    const pending = deferred<void>()
    ports.update.mockReturnValue(pending.promise)
    const view = mount({ files: [queuedFile({ status: 'parsed', markdownContent: 'Body' })], library: [libraryFile()] })
    let request!: Promise<void>
    act(() => {
      request = view.current().editor.handleSubmitToGovernance()
    })
    act(() =>
      view.current().page.setQueueFileParserBackend({ fileId: 'queue-a', filename: 'report.pdf', backend: 'marker' }),
    )
    await act(async () => {
      pending.resolve()
      await request
    })
    expect(view.current().files[0]).toMatchObject({ parserBackend: 'marker', governanceStatus: 'submitted' })
    expect(ports.push).toHaveBeenCalledWith('/data-governance')
    expect(ports.toast.error).not.toHaveBeenCalled()
  })

  it('retains a selected ready document when restoring its source into the queue', async () => {
    const view = mount({
      library: [
        libraryFile({
          source: undefined,
          markdownContent: 'Local body',
          originalMarkdownContent: 'Local original',
          governanceStatus: 'ready',
        }),
      ],
    })
    act(() => view.current().setSelectedGovernanceFileIds(new Set(['library-a'])))
    await act(async () => {
      await view.current().library.mountLibraryFileToQueue('library-a', new File(['Source'], 'report.md'))
    })
    expect(view.current().files[0].governanceStatus).toBe('ready')
    expect([...view.current().selectedGovernanceFileIds]).toEqual(['library-a'])
    ports.update.mockClear()
    await act(async () => {
      await view.current().editor.handleSubmitSelectedToGovernance()
    })
    expect(ports.update).toHaveBeenCalledTimes(1)
    expect(view.current().libraryFiles[0]).toMatchObject({
      governanceStatus: 'submitted',
      markdownContent: 'Local body',
      originalMarkdownContent: 'Local original',
    })
  })

  it('does not operate on a stale selection outside the current dataset scope', async () => {
    const view = mount({
      files: [
        queuedFile({ datasetId: 'dataset-a', status: 'parsed', markdownContent: 'First', governanceStatus: 'ready' }),
        queuedFile({
          id: 'queue-b',
          libraryId: 'library-b',
          datasetId: 'dataset-b',
          status: 'parsed',
          markdownContent: 'Second',
          governanceStatus: 'ready',
        }),
      ],
      library: [
        libraryFile({ datasetId: 'dataset-a', governanceStatus: 'ready' }),
        libraryFile({ id: 'library-b', datasetId: 'dataset-b', governanceStatus: 'ready' }),
      ],
    })
    act(() => view.current().page.setSelectedDatasetId('dataset-a'))
    act(() => view.current().setSelectedGovernanceFileIds(new Set(['library-a', 'library-b'])))
    await act(async () => {
      await view.current().editor.handleSubmitSelectedToGovernance()
    })
    expect(ports.update.mock.calls.map(([id]) => id)).toEqual(['library-a'])
    expect(view.current().files[1].governanceStatus).toBe('ready')
    expect([...view.current().selectedGovernanceFileIds]).toEqual(['library-b'])
  })

  it('reports a missing library identity instead of creating or saving a replacement', async () => {
    const view = mount({
      files: [
        queuedFile({ status: 'parsed', markdownContent: 'Body', libraryId: undefined, librarySource: undefined }),
      ],
    })
    act(() => view.current().editor.handleStartEdit())
    act(() => view.current().page.setEditedContent('Keep draft'))
    await act(async () => {
      await view.current().editor.handleSaveEdit()
    })
    expect(view.current().page.isEditing).toBe(true)
    expect(view.current().page.editedContent).toBe('Keep draft')
    expect(ports.toast.success).not.toHaveBeenCalled()
    await act(async () => {
      await view.current().editor.handleSubmitToGovernance()
    })
    expect(ports.update).not.toHaveBeenCalled()
    expect(ports.push).not.toHaveBeenCalled()
    expect(view.current().libraryFiles).toEqual([])
    expect(ports.toast.error).toHaveBeenLastCalledWith(expect.stringContaining('尚未加入文档库'))
  })

  it('keeps the selected source intact and blocks handoff when its run no longer exists', async () => {
    const runs = ['First', 'Latest'].map((value) => ({
      id: value,
      parserBackend: 'text',
      parserLabel: 'Text',
      rawMarkdown: `Raw ${value}`,
      cleanedMarkdown: value,
      blocks: [],
      createdAt: 0,
    }))
    const view = mount({
      files: [
        queuedFile({
          status: 'parsed',
          markdownContent: 'First',
          governanceStatus: 'ready',
          runs,
          activeRunId: 'removed-run',
        }),
      ],
      library: [libraryFile({ governanceStatus: 'ready' })],
    })
    expect(view.current().view.activeMarkdown).toBe('')
    expect(view.current().view.isRunUnavailable).toBe(true)
    act(() => view.current().setSelectedGovernanceFileIds(new Set(['library-a'])))
    await act(async () => {
      await view.current().editor.handleSubmitSelectedToGovernance()
    })
    expect(ports.update).not.toHaveBeenCalled()
    expect(ports.push).not.toHaveBeenCalled()
    expect(ports.toast.error).toHaveBeenCalledWith(expect.stringContaining('所选解析版本不可用'))
    expect(view.current().files[0].activeRunId).toBe('removed-run')
  })

  it('prevents a second handoff while the first submission is pending', async () => {
    const pending = deferred<void>()
    ports.update.mockReturnValue(pending.promise)
    const view = mount({
      files: [queuedFile({ status: 'parsed', markdownContent: 'Body', governanceStatus: 'ready' })],
      library: [libraryFile({ governanceStatus: 'ready' })],
    })
    let first!: Promise<void>
    act(() => {
      first = view.current().editor.handleSubmitToGovernance()
    })
    expect(view.current().editor.isSubmittingGovernance).toBe(true)
    await act(async () => {
      await view.current().editor.handleSubmitToGovernance()
    })
    expect(ports.update).toHaveBeenCalledTimes(1)
    await act(async () => {
      pending.resolve()
      await first
    })
    expect(ports.push).toHaveBeenCalledTimes(1)
    expect(view.current().editor.isSubmittingGovernance).toBe(false)
  })

  it.each(['scope', 'session', 'unmount'])(
    'does not navigate or publish success after %s invalidates a handoff',
    async (change) => {
      const pending = deferred<void>()
      ports.update.mockReturnValue(pending.promise)
      const view = mount({
        files: [queuedFile({ status: 'parsed', markdownContent: 'Body' })],
        library: [libraryFile()],
      })
      let request!: Promise<void>
      act(() => {
        request = view.current().editor.handleSubmitToGovernance()
      })
      if (change === 'scope') ports.authScope = 'next-scope'
      if (change === 'session') ports.authRevision += 1
      if (change === 'unmount') view.unmount()
      await act(async () => {
        pending.resolve()
        await request
      })
      expect(ports.push).not.toHaveBeenCalled()
      expect(ports.toast.success).not.toHaveBeenCalled()
    },
  )

  it('keeps a new selection and current view when a batch completes', async () => {
    const pending = deferred<void>()
    ports.update.mockReturnValue(pending.promise)
    const view = mount({
      files: [queuedFile({ status: 'parsed', markdownContent: 'Body', governanceStatus: 'ready' })],
      library: [libraryFile({ governanceStatus: 'ready' })],
    })
    act(() => view.current().setSelectedGovernanceFileIds(new Set(['library-a'])))
    let request!: Promise<void>
    act(() => {
      request = view.current().editor.handleSubmitSelectedToGovernance()
    })
    act(() => view.current().setSelectedGovernanceFileIds(new Set(['library-a', 'new-selection'])))
    await act(async () => {
      pending.resolve()
      await request
    })
    expect([...view.current().selectedGovernanceFileIds]).toEqual(['new-selection'])
    expect(ports.push).not.toHaveBeenCalled()
  })

  it('reports clipboard denial and never marks failed copying as successful', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error('Clipboard denied')) },
    })
    const view = mount({ files: [queuedFile({ status: 'parsed', markdownContent: 'Copy me' })] })
    await act(async () => {
      await view.current().editor.copyMarkdown()
    })
    expect(view.current().editor.copied).toBe(false)
    expect(ports.toast.error).toHaveBeenCalledWith(expect.stringContaining('Clipboard denied'))
  })

  it('does not show a delayed copy result on another selected file', async () => {
    const pending = deferred<void>()
    const copy = vi.fn().mockReturnValue(pending.promise)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: copy } })
    const view = mount({
      files: [
        queuedFile({ status: 'parsed', markdownContent: 'First' }),
        queuedFile({ id: 'queue-b', libraryId: 'library-b', status: 'parsed', markdownContent: 'Second' }),
      ],
    })
    let request!: Promise<void>
    act(() => {
      request = view.current().editor.copyMarkdown()
    })
    act(() => view.current().page.setActiveFileId('queue-b'))
    await act(async () => {
      pending.resolve()
      await request
    })
    expect(view.current().editor.copied).toBe(false)
  })

  it('restarts the copy feedback timeout for the most recent successful copy', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    })
    const view = mount({ files: [queuedFile({ status: 'parsed', markdownContent: 'Copy me' })] })
    await act(async () => {
      await view.current().editor.copyMarkdown()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000)
    })
    await act(async () => {
      await view.current().editor.copyMarkdown()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000)
    })
    expect(view.current().editor.copied).toBe(true)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000)
    })
    expect(view.current().editor.copied).toBe(false)
  })

  it('transfers processed text and the actual original run separately', async () => {
    const run = {
      id: 'run-a',
      parserBackend: 'text',
      parserLabel: 'Text',
      rawMarkdown: '',
      cleanedMarkdown: 'Processed',
      blocks: [],
      createdAt: 0,
    }
    const view = mount({
      files: [queuedFile({ status: 'parsed', markdownContent: 'Processed', runs: [run], activeRunId: run.id })],
      library: [libraryFile({ originalMarkdownContent: '' })],
    })
    await act(async () => {
      await view.current().editor.handleSubmitToGovernance()
    })
    expect(view.current().libraryFiles[0]).toMatchObject({
      markdownContent: 'Processed',
      originalMarkdownContent: '',
      governanceStatus: 'submitted',
    })
    expect(ports.push).toHaveBeenCalledWith('/data-governance')
  })

  it('transfers a known empty result once for linked queue and library records', async () => {
    const view = mount({
      files: [queuedFile({ status: 'parsed', markdownContent: '', governanceStatus: 'ready' })],
      library: [libraryFile({ markdownContent: '', originalMarkdownContent: '', governanceStatus: 'ready' })],
    })
    act(() => view.current().setSelectedGovernanceFileIds(new Set(['library-a'])))
    await act(async () => {
      await view.current().editor.handleSubmitSelectedToGovernance()
    })
    expect(ports.update).toHaveBeenCalledTimes(1)
    expect(view.current().files[0].governanceStatus).toBe('submitted')
    expect(view.current().libraryFiles[0]).toMatchObject({
      markdownContent: '',
      originalMarkdownContent: '',
      governanceStatus: 'submitted',
    })
  })

  it('transfers explicitly selected documents from multiple folders', async () => {
    const view = mount({
      files: [
        queuedFile({ status: 'parsed', markdownContent: 'Visible', governanceStatus: 'ready' }),
        queuedFile({
          id: 'hidden-queue',
          libraryId: 'hidden-library',
          folderId: 'other-folder',
          status: 'parsed',
          markdownContent: 'Hidden',
          governanceStatus: 'ready',
        }),
      ],
      library: [
        libraryFile({ markdownContent: 'Visible', governanceStatus: 'ready' }),
        libraryFile({
          id: 'hidden-library',
          folderId: 'other-folder',
          markdownContent: 'Hidden',
          governanceStatus: 'ready',
        }),
      ],
    })
    act(() => view.current().setSelectedGovernanceFileIds(new Set(['library-a', 'hidden-library'])))
    await act(async () => {
      await view.current().editor.handleSubmitSelectedToGovernance()
    })
    expect(ports.update.mock.calls.map(([id]) => id)).toEqual(['library-a', 'hidden-library'])
    expect(view.current().files[1].governanceStatus).toBe('submitted')
  })

  it('keeps failed selections after partial success and retries only the remaining files', async () => {
    ports.update.mockImplementation(async (id: string) => {
      if (id === 'library-b') throw new Error('Handoff denied')
    })
    const view = mount({
      files: [
        queuedFile({ status: 'parsed', markdownContent: 'First', governanceStatus: 'ready' }),
        queuedFile({
          id: 'queue-b',
          libraryId: 'library-b',
          status: 'parsed',
          markdownContent: 'Second',
          governanceStatus: 'ready',
        }),
      ],
      library: [
        libraryFile({ governanceStatus: 'ready' }),
        libraryFile({ id: 'library-b', governanceStatus: 'ready' }),
      ],
    })
    act(() => view.current().setSelectedGovernanceFileIds(new Set(['library-a', 'library-b'])))
    await act(async () => {
      await view.current().editor.handleSubmitSelectedToGovernance()
    })
    expect(view.current().files[0].governanceStatus).toBe('submitted')
    expect([...view.current().selectedGovernanceFileIds]).toEqual(['library-b'])
    expect(ports.push).not.toHaveBeenCalled()
    ports.update.mockResolvedValue(undefined)
    await act(async () => {
      await view.current().editor.handleSubmitSelectedToGovernance()
    })
    expect(ports.update.mock.calls.filter(([id]) => id === 'library-a')).toHaveLength(1)
    expect(view.current().selectedGovernanceFileIds.size).toBe(0)
    expect(ports.push).toHaveBeenCalledWith('/data-governance')
  })

  it('reads the full saved library body before transferring a library-only selection', async () => {
    ports.cache.getDocContentFromCache.mockResolvedValue({
      id: 'library-a',
      markdownContent: 'Saved body',
      originalMarkdownContent: 'Saved raw',
    })
    const view = mount({
      library: [
        libraryFile({ source: undefined, markdownContent: '', originalMarkdownContent: '', governanceStatus: 'ready' }),
      ],
    })
    act(() => view.current().setSelectedGovernanceFileIds(new Set(['library-a'])))
    await act(async () => {
      await view.current().editor.handleSubmitSelectedToGovernance()
    })
    expect(view.current().libraryFiles[0]).toMatchObject({
      markdownContent: 'Saved body',
      originalMarkdownContent: 'Saved raw',
      governanceStatus: 'submitted',
    })
  })
})

describe('local preview parsing and editing', () => {
  it('keeps the draft with its original file when the folder changes', () => {
    const view = mount({
      files: [
        queuedFile({ status: 'parsed', markdownContent: 'Original' }),
        queuedFile({
          id: 'queue-b',
          libraryId: 'library-b',
          folderId: 'root/other',
          status: 'parsed',
          markdownContent: 'Other file',
        }),
      ],
      library: [libraryFile(), libraryFile({ id: 'library-b', folderId: 'root/other' })],
    })

    act(() => view.current().editor.handleStartEdit())
    act(() => view.current().page.setEditedContent('Unsaved edit'))
    act(() => view.current().setActiveFolderId('root/other'))

    expect(view.current().view.activeFile?.id).toBe('queue-a')
    expect(view.current().page.editedContent).toBe('Unsaved edit')
  })

  it('keeps the newly selected run visible when an earlier run finishes saving', async () => {
    const pending = deferred<ParsingContentResponse>()
    ports.parsing.updateContent.mockReturnValue(pending.promise)
    const runs = ['first', 'second'].map((id) => ({
      id,
      parserBackend: 'text',
      parserLabel: 'Text',
      rawMarkdown: id,
      cleanedMarkdown: id,
      blocks: [],
      createdAt: 0,
    }))
    const view = mount({
      files: [queuedFile({ status: 'parsed', markdownContent: 'first', runs, activeRunId: 'first' })],
      library: [libraryFile()],
    })
    act(() => view.current().editor.handleStartEdit())
    act(() => view.current().page.setEditedContent('Edited first'))
    let request!: Promise<void>
    act(() => {
      request = view.current().editor.handleSaveEdit()
    })
    act(() => view.current().run.handleSelectRun('second'))
    await act(async () => {
      pending.resolve(content({ markdown_content: 'Edited first', original_markdown_content: 'Edited original' }))
      await request
    })
    expect(view.current().files[0].markdownContent).toBe('second')
    expect(view.current().view.activeMarkdown).toBe('second')
    expect(view.current().files[0].runs?.[0]).toMatchObject({
      cleanedMarkdown: 'Edited first',
      rawMarkdown: 'Edited original',
    })
  })

  it.each(['reparse', 'upload'])('does not cancel new-session queries when old %s cleanup finishes', async (action) => {
    const deletion = deferred<void>()
    const upload = deferred<ReturnType<typeof remoteDocument>>()
    ports.parsing.upload.mockReturnValue(upload.promise)
    ports.parsing.parse.mockRejectedValue(new Error('Parser unavailable'))
    ports.parsing.delete.mockReturnValue(deletion.promise)
    const view = mount({
      files: action === 'reparse' ? [queuedFile({ librarySource: undefined })] : [],
      library: [libraryFile({ source: undefined })],
    })
    const cancelQueries = vi.spyOn(view.client, 'cancelQueries')
    let request!: Promise<void>
    if (action === 'upload') {
      act(() =>
        view
          .current()
          .setFolders([{ id: 'target', name: 'Target', parentId: 'root', createdAt: '2026-11-13T00:00:00Z' }]),
      )
      act(() => {
        request = view.current().library.addFiles([new File(['Source'], 'a.md')], 'target')
      })
      act(() => view.current().setFolders([]))
    } else {
      act(() => {
        request = view.current().run.parseFile('queue-a')
      })
    }
    await act(async () => {
      upload.resolve(remoteDocument('server-a'))
    })
    await settle()
    expect(ports.parsing.delete).toHaveBeenCalledWith('server-a')
    ports.authRevision += 1
    await act(async () => {
      deletion.resolve()
      await request
    })
    expect(cancelQueries).not.toHaveBeenCalled()
  })

  it('removes a provisional server entry already discovered by library synchronization', async () => {
    const pending = deferred<ParsingContentResponse>()
    ports.parsing.upload.mockResolvedValue(remoteDocument('server-a'))
    ports.parsing.parse.mockReturnValue(pending.promise)
    const original = libraryFile({ source: undefined, markdownContent: 'Keep preview' })
    const view = mount({ files: [queuedFile({ librarySource: undefined })], library: [original], loaded: true })
    await settle()
    let request!: Promise<void>
    act(() => {
      request = view.current().run.parseFile('queue-a')
    })
    await settle()
    ports.parsing.listDocuments.mockResolvedValue({ total: 1, items: [remoteDocument('server-a')] })
    await act(async () => {
      await view.client.invalidateQueries({ queryKey: ['parsing', 'library-snapshot'] })
    })
    await settle()
    expect(view.current().libraryFiles.map((file) => file.id)).toEqual(['library-a', 'server-a'])
    ports.parsing.delete.mockImplementation(async () => {
      ports.parsing.listDocuments.mockResolvedValue({ total: 0, items: [] })
    })
    await act(async () => {
      pending.reject(new Error('Parser unavailable'))
      await request
    })
    await settle()
    expect(view.current().libraryFiles).toEqual([original])
    expect(ports.remove).toHaveBeenCalledWith('server-a')
  })

  it.each(['scope', 'session', 'unmount', 'removed'])(
    'does not publish an edit after %s invalidates its owner',
    async (change) => {
      const pending = deferred<ParsingContentResponse>()
      ports.parsing.updateContent.mockReturnValue(pending.promise)
      const view = mount({
        files: [queuedFile({ status: 'parsed', markdownContent: 'Before' })],
        library: [libraryFile()],
      })
      act(() => view.current().editor.handleStartEdit())
      act(() => view.current().page.setEditedContent('Draft'))
      let request!: Promise<void>
      act(() => {
        request = view.current().editor.handleSaveEdit()
      })
      if (change === 'scope') ports.authScope = 'next-scope'
      if (change === 'session') ports.authRevision += 1
      if (change === 'unmount') view.unmount()
      if (change === 'removed')
        act(() => {
          view.current().setFiles([])
          view.current().setLibraryFiles([])
        })
      await act(async () => {
        pending.resolve(content())
        await request
      })
      expect(ports.update).not.toHaveBeenCalled()
      expect(ports.toast.success).not.toHaveBeenCalled()
    },
  )

  it('retains a newer edit while an earlier submitted draft is being saved', async () => {
    const pending = deferred<ParsingContentResponse>()
    ports.parsing.updateContent.mockReturnValue(pending.promise)
    const view = mount({
      files: [queuedFile({ status: 'parsed', markdownContent: 'Before' })],
      library: [libraryFile()],
    })
    act(() => view.current().editor.handleStartEdit())
    act(() => view.current().page.setEditedContent('Submitted'))
    let request!: Promise<void>
    act(() => {
      request = view.current().editor.handleSaveEdit()
    })
    act(() => view.current().page.setEditedContent('Newer draft'))
    await act(async () => {
      pending.resolve(content({ markdown_content: 'Submitted' }))
      await request
    })
    expect(view.current().files[0].markdownContent).toBe('Submitted')
    expect(view.current().page.isEditing).toBe(true)
    expect(view.current().page.editedContent).toBe('Newer draft')
  })

  it('does not rewrite the local record when mounting its source for automatic reparse', async () => {
    const original = libraryFile({ source: undefined, filename: 'original.pdf', markdownContent: 'Keep preview' })
    const pending = deferred<ReturnType<typeof remoteDocument>>()
    ports.parsing.upload.mockReturnValue(pending.promise)
    const view = mount({ library: [original] })
    await act(async () => {
      await view
        .current()
        .library.mountLibraryFileToQueue(original.id, new File(['new source'], 'new.pdf'), { autoParse: true })
    })
    expect(view.current().libraryFiles).toEqual([original])
    expect(view.current().files[0].markdownContent).toBe('Keep preview')
    await act(async () => {
      pending.reject(new Error('Upload failed'))
    })
  })

  it('cleans up a cancelled conversion without replacing the preview', async () => {
    const pending = deferred<ParsingContentResponse>()
    ports.parsing.upload.mockResolvedValue(remoteDocument('server-a'))
    ports.parsing.parse.mockReturnValue(pending.promise)
    const original = libraryFile({ source: undefined, markdownContent: 'Keep preview' })
    const view = mount({ files: [queuedFile({ librarySource: undefined })], library: [original] })
    let request!: Promise<void>
    act(() => {
      request = view.current().run.parseFile('queue-a')
    })
    await settle()
    act(() => view.current().page.cancelParse('queue-a'))
    await act(async () => {
      pending.resolve(content())
      await request
    })
    expect(view.current().libraryFiles).toEqual([original])
    expect(ports.parsing.delete).toHaveBeenCalledWith('server-a')
    expect(ports.replace).not.toHaveBeenCalled()
  })

  it('keeps the original when replacement persistence fails and reports failed server cleanup', async () => {
    ports.parsing.upload.mockResolvedValue(remoteDocument('server-a'))
    ports.parsing.parse.mockResolvedValue(content())
    ports.replace.mockImplementationOnce(() => {
      throw new Error('Library index unavailable')
    })
    ports.parsing.delete.mockRejectedValue(new Error('Cleanup denied'))
    const original = libraryFile({ source: undefined, markdownContent: 'Keep preview' })
    const view = mount({ files: [queuedFile({ librarySource: undefined })], library: [original] })
    await act(async () => {
      await view.current().run.parseFile('queue-a')
    })
    expect(view.current().libraryFiles).toEqual([original])
    expect(view.current().files[0].error).toContain('Library index unavailable')
    expect(ports.toast.warning).toHaveBeenCalledWith(expect.stringContaining('清理失败'))
  })

  it('replaces the original entry only after full parsing succeeds', async () => {
    const pending = deferred<ParsingContentResponse>()
    ports.parsing.upload.mockResolvedValue(remoteDocument('server-a', { status: 'pending' }))
    ports.parsing.parse.mockReturnValue(pending.promise)
    const original = libraryFile({ source: undefined, markdownContent: 'Original preview' })
    const view = mount({
      files: [queuedFile({ librarySource: undefined, status: 'parsed', markdownContent: 'Original preview' })],
      library: [original],
    })
    let request!: Promise<void>
    act(() => {
      request = view.current().run.parseFile('queue-a')
    })
    await settle()

    expect(ports.parsing.upload).toHaveBeenCalledTimes(1)
    expect(ports.parsing.parse).toHaveBeenCalledWith(
      'server-a',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(view.current().libraryFiles).toEqual([original])
    await act(async () => {
      await view.current().queue.moveFileToFolder('queue-a', 'moved-folder')
    })
    await act(async () => {
      pending.resolve(
        content({
          document_id: 'server-a',
          markdown_content: '',
          original_markdown_content: 'Raw',
          parse_duration_sec: 0,
        }),
      )
      await request
    })

    expect(view.current().libraryFiles).toEqual([
      expect.objectContaining({
        id: 'server-a',
        source: 'parsing_workspace',
        markdownContent: '',
        originalMarkdownContent: 'Raw',
        durationSec: 0,
        folderId: 'moved-folder',
      }),
    ])
    expect(view.current().files[0]).toMatchObject({
      libraryId: 'server-a',
      librarySource: 'parsing_workspace',
      status: 'parsed',
      markdownContent: '',
    })
    expect(ports.parsing.delete).not.toHaveBeenCalled()
  })

  it('retains the original record and removes an unsuccessful server upload', async () => {
    ports.parsing.upload.mockResolvedValue(remoteDocument('server-a', { status: 'pending' }))
    ports.parsing.parse.mockRejectedValue(new Error('Parser unavailable'))
    const original = libraryFile({
      source: undefined,
      markdownContent: 'Keep preview',
      originalMarkdownContent: 'Keep raw',
    })
    const view = mount({
      files: [queuedFile({ librarySource: undefined, status: 'parsed', markdownContent: 'Keep preview' })],
      library: [original],
    })

    await act(async () => {
      await view.current().run.parseFile('queue-a')
    })

    expect(ports.parsing.upload).toHaveBeenCalledTimes(1)
    expect(ports.parsing.delete).toHaveBeenCalledWith('server-a')
    expect(view.current().libraryFiles).toEqual([original])
    expect(view.current().files[0]).toMatchObject({
      libraryId: 'library-a',
      librarySource: undefined,
      status: 'error',
      markdownContent: 'Keep preview',
    })
  })

  it('keeps the preview when upload fails before a server ID exists', async () => {
    ports.parsing.upload.mockRejectedValue(new Error('Upload denied'))
    const original = libraryFile({ source: undefined, markdownContent: 'Keep preview' })
    const view = mount({ files: [queuedFile({ librarySource: undefined })], library: [original] })

    await act(async () => {
      await view.current().run.parseFile('queue-a')
    })

    expect(view.current().libraryFiles).toEqual([original])
    expect(ports.parsing.parse).not.toHaveBeenCalled()
    expect(ports.parsing.delete).not.toHaveBeenCalled()
  })

  it('saves a genuine local preview through the local content owner', async () => {
    const view = mount({
      files: [queuedFile({ librarySource: undefined, status: 'parsed', markdownContent: 'Before' })],
      library: [libraryFile({ source: undefined })],
    })
    act(() => view.current().editor.handleStartEdit())
    act(() => view.current().page.setEditedContent(''))

    await act(async () => {
      await view.current().editor.handleSaveEdit()
    })

    expect(ports.parsing.updateContent).not.toHaveBeenCalled()
    expect(ports.update).toHaveBeenCalledWith('library-a', expect.objectContaining({ markdownContent: '' }), {
      requirePersistence: true,
    })
    expect(view.current().libraryFiles[0]).toMatchObject({
      id: 'library-a',
      markdownContent: '',
      originalMarkdownContent: '',
      governanceStatus: 'ready',
    })
    expect(view.current().page.isEditing).toBe(false)
  })

  it('retains a local edit when its durable save fails', async () => {
    ports.update.mockRejectedValue(new Error('Browser write denied'))
    const original = libraryFile({ source: undefined, markdownContent: 'Before' })
    const view = mount({
      files: [queuedFile({ librarySource: undefined, status: 'parsed', markdownContent: 'Before' })],
      library: [original],
    })
    act(() => view.current().editor.handleStartEdit())
    act(() => view.current().page.setEditedContent('Keep my draft'))
    await act(async () => {
      await view.current().editor.handleSaveEdit()
    })
    expect(view.current().page.isEditing).toBe(true)
    expect(view.current().page.editedContent).toBe('Keep my draft')
    expect(view.current().libraryFiles).toEqual([original])
    expect(ports.parsing.updateContent).not.toHaveBeenCalled()
    expect(ports.toast.success).not.toHaveBeenCalled()
    expect(ports.toast.error).toHaveBeenCalledWith(expect.stringContaining('Browser write denied'))
  })
})

describe('queue operation confirmation', () => {
  it('keeps a creating upload until the server document identity is available for deletion', async () => {
    const pending = deferred<ReturnType<typeof remoteDocument>>()
    ports.parsing.upload.mockReturnValue(pending.promise)
    ports.parsing.parse.mockResolvedValue(content({ document_id: 'created-a' }))
    const view = mount({ files: [queuedFile({ libraryId: undefined })] })
    let request!: Promise<void>
    act(() => {
      request = view.current().run.parseFile('queue-a')
    })
    await settle()
    await act(async () => {
      await expect(view.current().queue.removeFile('queue-a')).rejects.toThrow('正在上传')
    })
    expect(view.current().files).toHaveLength(1)
    await act(async () => {
      pending.resolve(remoteDocument('created-a', { status: 'pending' }))
      await request
    })
    await act(async () => {
      await view.current().queue.removeFile('queue-a')
    })
    expect(ports.parsing.delete).toHaveBeenCalledWith('created-a')
    expect(view.current().files).toEqual([])
    expect(view.current().libraryFiles).toEqual([])
  })

  it('retains the moved folder when parsing finishes', async () => {
    const pending = deferred<ParsingContentResponse>()
    ports.parsing.parse.mockReturnValue(pending.promise)
    const view = mount({ files: [queuedFile()], library: [libraryFile()] })
    let request!: Promise<void>
    act(() => {
      request = view.current().run.parseFile('queue-a')
    })
    await settle()
    await act(async () => {
      await view.current().queue.moveFileToFolder('queue-a', 'moved-folder')
    })
    await act(async () => {
      pending.resolve(content())
      await request
    })
    expect(view.current().files[0].folderId).toBe('moved-folder')
    expect(view.current().libraryFiles[0].folderId).toBe('moved-folder')
  })
  it('checks the existing library read error before starting a remote deletion', async () => {
    const failure = new Error('Stored library unreadable')
    ports.libraryError = failure
    const view = mount({ files: [queuedFile()], library: [libraryFile()] })
    await act(async () => {
      await expect(view.current().queue.removeFile('queue-a')).rejects.toBe(failure)
    })
    expect(ports.parsing.delete).not.toHaveBeenCalled()
    expect(ports.remove).not.toHaveBeenCalled()
  })

  it.each(['unmount', 'scope', 'session'])(
    'does not publish a deletion after %s invalidates its owner',
    async (change) => {
      const pending = deferred<void>()
      ports.parsing.delete.mockReturnValue(pending.promise)
      const view = mount({ files: [queuedFile()], library: [libraryFile()] })
      let request!: Promise<void> | void
      act(() => {
        request = view.current().queue.removeFile('queue-a')
      })
      if (change === 'unmount') view.unmount()
      if (change === 'scope') ports.authScope = 'new-scope'
      if (change === 'session') ports.authRevision += 1
      await act(async () => {
        pending.resolve()
        await request
      })
      expect(ports.remove).not.toHaveBeenCalled()
    },
  )

  it('clears only selections belonging to the confirmed deletion', async () => {
    const view = mount({ files: [queuedFile()], library: [libraryFile()] })
    act(() => view.current().setSelectedGovernanceFileIds(new Set(['queue-a', 'library-a', 'queue-b'])))
    await act(async () => {
      await view.current().queue.removeFile('queue-a')
    })
    expect([...view.current().selectedGovernanceFileIds]).toEqual(['queue-b'])
  })
  it('retains both representations until remote deletion succeeds', async () => {
    const pending = deferred<void>()
    ports.parsing.delete.mockReturnValue(pending.promise)
    const view = mount({ files: [queuedFile()], library: [libraryFile()] })
    let request!: Promise<void> | void
    act(() => {
      request = view.current().queue.removeFile('queue-a')
    })
    try {
      expect(view.current().files).toHaveLength(1)
      expect(view.current().libraryFiles).toHaveLength(1)
      expect(ports.remove).not.toHaveBeenCalled()
    } finally {
      await act(async () => {
        pending.resolve()
        await request
      })
    }
    expect(view.current().files).toEqual([])
    expect(view.current().libraryFiles).toEqual([])
  })

  it('propagates failed deletion while preserving the queue and saved record', async () => {
    const failure = new Error('Delete denied')
    ports.parsing.delete.mockRejectedValue(failure)
    const view = mount({ files: [queuedFile()], library: [libraryFile()] })
    await act(async () => {
      await expect(view.current().queue.removeFile('queue-a')).rejects.toBe(failure)
    })

    expect(view.current().files).toHaveLength(1)
    expect(view.current().libraryFiles).toHaveLength(1)
    expect(ports.remove).not.toHaveBeenCalled()
    expect(ports.cache.deleteDocContentFromCache).not.toHaveBeenCalled()
  })

  it('removes a real local preview without guessing a server document', async () => {
    const view = mount({ library: [libraryFile({ source: undefined })] })
    await act(async () => {
      await view.current().queue.removeFile('library-a')
    })

    expect(view.current().libraryFiles).toEqual([])
    expect(ports.parsing.delete).not.toHaveBeenCalled()
    expect(ports.documents.delete).not.toHaveBeenCalled()
    expect(ports.cache.deleteDocContentFromCache).not.toHaveBeenCalled()
    expect(ports.cache.deleteDocSourceFromCache).not.toHaveBeenCalled()
  })

  it('keeps a newer selected file when the earlier deletion finishes', async () => {
    const pending = deferred<void>()
    ports.parsing.delete.mockReturnValue(pending.promise)
    const view = mount({
      files: [queuedFile(), queuedFile({ id: 'queue-b', libraryId: 'library-b' })],
      library: [libraryFile(), libraryFile({ id: 'library-b' })],
    })
    let request!: Promise<void> | void
    act(() => {
      request = view.current().queue.removeFile('queue-a')
    })
    act(() => view.current().page.setActiveFileId('queue-b'))
    await act(async () => {
      pending.resolve()
      await request
    })

    expect(view.current().page.activeFileId).toBe('queue-b')
    expect(view.current().files.map((file) => file.id)).toEqual(['queue-b'])
  })

  it('waits for the folder update before changing the queue projection', async () => {
    const pending = deferred<void>()
    ports.update.mockReturnValue(pending.promise)
    const view = mount({ files: [queuedFile()], library: [libraryFile()] })
    let request!: Promise<void> | void
    act(() => {
      request = view.current().queue.moveFileToFolder('queue-a', 'target-folder')
    })
    try {
      expect(view.current().files[0].folderId).toBe('root')
    } finally {
      await act(async () => {
        pending.resolve()
        await request
      })
    }
    expect(view.current().files[0].folderId).toBe('target-folder')
  })
})

describe('directory upload dataset ownership', () => {
  it('keeps the library selection made while an earlier upload was pending', async () => {
    const pending = deferred<ReturnType<typeof remoteDocument>>()
    ports.parsing.upload.mockReturnValue(pending.promise)
    const view = mount({ library: [libraryFile({ id: 'library-b' })] })
    let request!: Promise<void>
    act(() => {
      request = view.current().library.addFiles([new File(['Source'], 'a.md')])
    })
    act(() => view.current().page.setActiveLibraryFileId('library-b'))
    await act(async () => {
      pending.resolve(remoteDocument('uploaded-a'))
      await request
    })
    expect(view.current().page.activeFileId).toBeNull()
    expect(view.current().page.activeLibraryFileId).toBe('library-b')
  })

  it.each(['plain', 'directory'])(
    'cancels a %s upload whose target folder was deleted during the request',
    async (kind) => {
      const pending = deferred<ReturnType<typeof remoteDocument>>()
      ports.parsing.upload.mockReturnValue(pending.promise)
      const view = mount()
      act(() => {
        view
          .current()
          .setFolders([{ id: 'target', name: 'target', parentId: 'root', createdAt: '2026-11-13T00:00:00Z' }])
      })
      const file = new File(['Source'], 'a.md')
      if (kind === 'directory') Object.defineProperty(file, 'webkitRelativePath', { value: 'nested/a.md' })
      let request!: Promise<void>
      act(() => {
        request = view.current().library.addFiles([file], 'target')
      })
      await settle()
      act(() => view.current().setFolders([]))
      await act(async () => {
        pending.resolve(remoteDocument('uploaded-a'))
        await request
      })
      expect(ports.parsing.delete).toHaveBeenCalledWith('uploaded-a')
      expect(view.current().libraryFiles).toEqual([])
      expect(view.current().files).toEqual([])
      expect(ports.toast.success).not.toHaveBeenCalled()
    },
  )

  it('enqueues plain, directory and real ZIP sources with the same metadata contract', async () => {
    vi.useRealTimers()
    const archive = new JSZip()
    archive.file('project/nested/c.md', 'ZIP body')
    archive.file('unsupported.exe', 'skip')
    const zipBytes = await archive.generateAsync({ type: 'arraybuffer' })
    const directoryFile = new File(['Directory body'], 'b.md')
    Object.defineProperty(directoryFile, 'webkitRelativePath', { value: 'project/nested/b.md' })
    ports.parsing.upload.mockImplementation(async (file: File) => remoteDocument(file.name))
    const view = mount()
    await act(async () => {
      await view
        .current()
        .library.addFiles([new File(['Plain'], 'a.md'), directoryFile, new File([zipBytes], 'sources.zip')])
    })
    expect(
      view.current().files.map((file) => ({
        name: file.name,
        folderId: file.folderId,
        sourcePath: file.sourcePath,
        status: file.status,
        librarySource: file.librarySource,
      })),
    ).toEqual([
      { name: 'a.md', folderId: 'root', sourcePath: undefined, status: 'pending', librarySource: 'parsing_workspace' },
      {
        name: 'b.md',
        folderId: 'root/project/nested',
        sourcePath: 'project/nested/b.md',
        status: 'pending',
        librarySource: 'parsing_workspace',
      },
      {
        name: 'c.md',
        folderId: 'root/project/nested',
        sourcePath: 'project/nested/c.md',
        status: 'pending',
        librarySource: 'parsing_workspace',
      },
    ])
    expect(ports.parsing.upload).toHaveBeenCalledTimes(3)
    expect(await view.current().files[2].file.text()).toBe('ZIP body')
    expect(ports.toast.warning).toHaveBeenCalledWith('已跳过 1 个不支持的文件')
  })

  it('publishes the current library folder after an earlier upload was moved during its batch', async () => {
    const pending = deferred<ReturnType<typeof remoteDocument>>()
    ports.parsing.upload.mockResolvedValueOnce(remoteDocument('uploaded-a')).mockReturnValueOnce(pending.promise)
    const view = mount()
    act(() =>
      view
        .current()
        .setFolders([
          { id: 'moved-folder', name: 'Moved folder', parentId: 'root', createdAt: '2026-11-13T00:00:00Z' },
        ]),
    )
    let request!: Promise<void>
    act(() => {
      request = view.current().library.addFiles([new File(['a'], 'a.md'), new File(['b'], 'b.md')])
    })
    await settle()
    await act(async () => {
      await view.current().queue.moveFileToFolder('uploaded-a', 'moved-folder')
    })
    await act(async () => {
      pending.resolve(remoteDocument('uploaded-b'))
      await request
    })
    expect(view.current().files.find((file) => file.libraryId === 'uploaded-a')?.folderId).toBe('moved-folder')
    expect(view.current().libraryFiles.find((file) => file.id === 'uploaded-a')?.folderId).toBe('moved-folder')
  })
  it('does not republish an uploaded record deleted while the rest of its batch was uploading', async () => {
    const pending = deferred<ReturnType<typeof remoteDocument>>()
    ports.parsing.upload.mockResolvedValueOnce(remoteDocument('uploaded-a')).mockReturnValueOnce(pending.promise)
    const view = mount()
    let request!: Promise<void>
    act(() => {
      request = view.current().library.addFiles([new File(['a'], 'a.md'), new File(['b'], 'b.md')])
    })
    await settle()
    await act(async () => {
      await view.current().queue.removeFile('uploaded-a')
    })
    await act(async () => {
      pending.resolve(remoteDocument('uploaded-b'))
      await request
    })
    expect(view.current().files.map((file) => file.libraryId)).toEqual(['uploaded-b'])
  })
  it('keeps the acknowledged server identity when saving its library metadata fails', async () => {
    ports.parsing.upload.mockResolvedValue(remoteDocument('uploaded-a'))
    ports.upsert.mockImplementationOnce(() => {
      throw new Error('Metadata write failed')
    })
    const view = mount()
    await act(async () => {
      await view.current().library.addFiles([new File(['source'], 'report.md')])
    })
    expect(view.current().files[0]).toMatchObject({
      status: 'error',
      libraryId: 'uploaded-a',
      librarySource: 'parsing_workspace',
    })
    await act(async () => {
      await view.current().queue.removeFile(view.current().files[0].id)
    })
    expect(ports.parsing.delete).toHaveBeenCalledWith('uploaded-a')
  })

  it('uses the actual server filename, time and valid zero file size', async () => {
    ports.parsing.upload.mockResolvedValue(remoteDocument('uploaded-a', { filename: 'server.md', file_size: 0 }))
    const view = mount()
    await act(async () => {
      await view.current().library.addFiles([new File(['nonempty source'], 'client.md')])
    })
    expect(view.current().libraryFiles[0]).toMatchObject({
      filename: 'server.md',
      fileSize: 0,
      parsedAt: '2026-11-13T00:00:00Z',
    })
  })
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
    ports.parsing.upload.mockResolvedValue(
      remoteDocument('uploaded-a', {
        status: 'completed',
        metadata: { target_dataset_id: ' dataset-a ', target_dataset_name: ' Dataset A ' },
      }),
    )
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
