// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Document } from '@/types/backend'
import type { CleanPreviewResponse, GovernanceAnalyzeResponse } from '@/types/processing'
import { PipelineOptionsProvider } from '@/contexts/pipeline-options-context'
import { ROOT_FOLDER_ID, useParsedFiles, type ParsedFileData } from '@/store/use-parsed-files-store'
import { waitForAssertion } from '@/test/hook-harness'

const boundary = vi.hoisted(() => ({
  search: 'tab=classify',
  router: { push: vi.fn(), replace: vi.fn() },
  listDatasets: vi.fn(),
  listParsing: vi.fn(),
  listKnowledge: vi.fn(),
  parsingContent: vi.fn(),
  knowledgeContent: vi.fn(),
  deleteParsing: vi.fn(),
  preview: vi.fn(),
  extractZip: vi.fn(),
  governanceAnalyze: vi.fn(),
  autoAnnotations: vi.fn(),
  cleanPreview: vi.fn(),
  llmCleanPreview: vi.fn(),
  listPrompts: vi.fn(),
  cachedContent: vi.fn(),
  saveContent: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  reportWarning: vi.fn(),
}))

vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api', () => ({
  datasetApi: { listAll: boundary.listDatasets },
  documentApi: { list: boundary.listKnowledge, getParsedContent: boundary.knowledgeContent, preview: boundary.preview },
  parsingApi: {
    listDocuments: boundary.listParsing,
    getContent: boundary.parsingContent,
    delete: boundary.deleteParsing,
  },
}))
vi.mock('@/lib/api/datasets', () => ({ datasetApi: { listAll: boundary.listDatasets } }))
vi.mock('@/lib/api/documents', () => ({
  documentApi: { list: boundary.listKnowledge, getParsedContent: boundary.knowledgeContent, preview: boundary.preview },
}))
vi.mock('@/lib/api/parsing', () => ({
  parsingApi: {
    listDocuments: boundary.listParsing,
    getContent: boundary.parsingContent,
    delete: boundary.deleteParsing,
  },
}))
vi.mock('@/lib/api/pipeline', () => ({ pipelineApi: boundary }))
vi.mock('@/lib/api/prompts', () => ({ promptTemplateApi: { list: boundary.listPrompts } }))
vi.mock('@/lib/auth-storage', () => ({
  AUTH_SCOPE_CHANGED_EVENT: 'mimirq:auth-scope-changed',
  getAuthCacheScope: () => 'tenant-a:user-a',
}))
vi.mock('@/lib/doc-content-cache', () => ({
  getDocContentFromCache: boundary.cachedContent,
  saveDocContentToCache: boundary.saveContent,
  clearDocCachesForScope: vi.fn(),
  deleteDocContentFromCache: vi.fn(),
  deleteDocSourceFromCache: vi.fn(),
  invalidateDocCacheScopeWrites: vi.fn(),
}))
vi.mock('@/lib/zip', () => ({
  isZipFile: (file: File) => file.name.endsWith('.zip'),
  extractZipFiles: boundary.extractZip,
}))
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn(), reportClientWarning: boundary.reportWarning }))
vi.mock('sonner', () => ({
  toast: { success: boundary.success, warning: boundary.warning, error: boundary.error, info: boundary.info },
}))
vi.mock('next/navigation', () => {
  const params = new Map<string, URLSearchParams>()
  return {
    useSearchParams: () => {
      if (!params.has(boundary.search)) params.set(boundary.search, new URLSearchParams(boundary.search))
      return params.get(boundary.search)
    },
  }
})
vi.mock('@/i18n/navigation', () => ({ useRouter: () => boundary.router }))
vi.mock('@/contexts/parser-backend-context', () => ({ useParserBackendPreference: () => ({ parserBackend: 'auto' }) }))
vi.mock('next-intl', () => {
  const translations = new Map<string, ReturnType<typeof makeTranslation>>()
  function makeTranslation(namespace: string) {
    return Object.assign(
      (key: string, values?: Record<string, string | number>) =>
        `${namespace}.${key}${values ? ` ${JSON.stringify(values)}` : ''}`,
      { raw: () => ['Preset tag'] },
    )
  }
  return {
    useTranslations: (namespace: string) => {
      if (!translations.has(namespace)) translations.set(namespace, makeTranslation(namespace))
      return translations.get(namespace)
    },
  }
})
vi.mock('next/image', () => ({
  // eslint-disable-next-line @next/next/no-img-element -- Image transport is outside the workflow owner.
  default: ({ src, alt }: { src: string; alt: string }) => <img src={src} alt={alt} />,
}))
vi.mock('@/components/markdown/markdown-renderer', () => ({
  MarkdownRenderer: ({ markdown }: { markdown: string }) => <pre data-displayed-content>{markdown}</pre>,
}))
vi.mock('@/components/pipeline-options-panel', () => ({ PipelineOptionsPanel: () => null }))
vi.mock('@/components/governance-profile-selector', () => ({ GovernanceProfileSelector: () => null }))

import { DataGovernancePanel } from './data-governance-panel'

const ORIGINAL = 'Alpha original source text with enough content for governance workflows.'
const cleanups: Array<() => void> = []

function localFile(id = 'file-a', overrides: Partial<ParsedFileData> = {}): ParsedFileData {
  return {
    id,
    filename: `${id}.md`,
    fileType: 'md',
    fileSize: 80,
    markdownContent: ORIGINAL,
    originalMarkdownContent: ORIGINAL,
    parser: 'auto',
    parsedAt: '2026-11-05T00:00:00Z',
    folderId: ROOT_FOLDER_ID,
    status: 'parsed',
    ...overrides,
  }
}

function remoteDocument(id: string, overrides: Partial<Document> = {}): Document {
  return {
    id,
    filename: `${id}.md`,
    file_type: 'md',
    file_size: 80,
    status: 'completed',
    processing_progress: 100,
    processing_attempts: 0,
    publication_status: 'published',
    chunk_count: 0,
    total_characters: ORIGINAL.length,
    created_at: '2026-11-05T00:00:00Z',
    updated_at: '2026-11-05T00:00:00Z',
    ...overrides,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept
    reject = fail
  })
  return { promise, resolve, reject }
}

async function mount(files = [localFile()]) {
  useParsedFiles.setState({ files, folders: [], activeFolderId: ROOT_FOLDER_ID, isLoaded: true })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  let mounted = true
  const unmount = () => {
    if (!mounted) return
    mounted = false
    act(() => root.unmount())
    client.clear()
    container.remove()
  }
  cleanups.push(unmount)
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <PipelineOptionsProvider>
          <DataGovernancePanel />
        </PipelineOptionsProvider>
      </QueryClientProvider>,
    )
  })
  return { container, client, unmount }
}

function button(container: ParentNode, text: string) {
  const match = [...container.querySelectorAll('button')].find(
    (item) => item.textContent?.includes(text) || item.getAttribute('aria-label')?.includes(text),
  )
  expect(match, `button ${text}`).toBeDefined()
  return match!
}

async function click(container: ParentNode, text: string) {
  await act(async () => button(container, text).click())
}

async function type(input: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  await act(async () => {
    Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

async function upload(container: HTMLElement, files: File[]) {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]')!
  await act(async () => {
    Object.defineProperty(input, 'files', { configurable: true, value: files })
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

async function markMetadataModified(container: HTMLElement) {
  await click(container, 'DataClassifier.categories.technical.label')
  expect(button(container, 'DataGovernancePanel.actions.reset').disabled).toBe(false)
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.resetAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  boundary.search = 'tab=classify'
  boundary.listDatasets.mockResolvedValue([])
  boundary.listParsing.mockResolvedValue({ total: 0, items: [] })
  boundary.listKnowledge.mockResolvedValue({ total: 0, items: [] })
  boundary.cachedContent.mockResolvedValue(null)
  boundary.saveContent.mockResolvedValue(undefined)
  boundary.listPrompts.mockResolvedValue({ total: 0, items: [] })
  boundary.governanceAnalyze.mockResolvedValue({ issues: [] })
  boundary.cleanPreview.mockResolvedValue({ markdown: 'Cleaned content', applied_rules: 1, changed: true })
  boundary.llmCleanPreview.mockResolvedValue({ markdown: 'LLM content', changed: true, warnings: [] })
})

afterEach(() => {
  cleanups
    .splice(0)
    .reverse()
    .forEach((dispose) => dispose())
  useParsedFiles.setState({ files: [], folders: [], activeFolderId: ROOT_FOLDER_ID, isLoaded: false })
  document.body.replaceChildren()
})

describe('parent reset intent', () => {
  it.each(['resolve', 'reject'] as const)(
    'retires a cleaner %s when global reset keeps the same text',
    async (settlement) => {
      const old = deferred<CleanPreviewResponse>()
      boundary.cleanPreview.mockReturnValueOnce(old.promise)
      const view = await mount()
      await markMetadataModified(view.container)
      await click(view.container, 'DataGovernancePanel.tabs.clean.label')
      await click(view.container, 'DataCleaner.llm.enable')
      await click(view.container, 'DataCleaner.actions.apply')
      expect(boundary.cleanPreview).toHaveBeenCalledOnce()

      await click(view.container, 'DataGovernancePanel.actions.reset')
      expect(view.container.querySelector('[data-displayed-content]')?.textContent).toBe(ORIGINAL)
      await act(async () => {
        if (settlement === 'resolve')
          old.resolve({ markdown: 'Discarded stale clean', changed: true, applied_rules: 1 })
        else old.reject(new Error('Discarded stale error'))
      })

      expect(view.container.querySelector('[data-displayed-content]')?.textContent).toBe(ORIGINAL)
      expect(view.container.textContent).not.toContain('Discarded stale')
      expect(boundary.llmCleanPreview).not.toHaveBeenCalled()
      expect(button(view.container, 'DataCleaner.actions.apply').disabled).toBe(false)
      expect(button(view.container, 'DataCleaner.llm.enabled')).toBeDefined()
    },
  )

  it('retires a quality scan when global reset changes metadata but not content or zero score', async () => {
    const old = deferred<GovernanceAnalyzeResponse>()
    boundary.governanceAnalyze.mockReturnValue(old.promise)
    const view = await mount()
    await markMetadataModified(view.container)
    await click(view.container, 'DataGovernancePanel.tabs.quality.label')
    expect(boundary.governanceAnalyze).toHaveBeenCalledOnce()

    await click(view.container, 'DataGovernancePanel.actions.reset')
    await act(async () =>
      old.resolve({ issues: [{ code: 'stale', severity: 'error', message: 'Discarded stale quality' }] }),
    )

    expect(view.container.textContent).not.toContain('Discarded stale quality')
    expect(view.container.textContent).not.toContain('QualityChecker.score.title')
    expect(button(view.container, 'QualityChecker.actions.scan').disabled).toBe(false)
    expect(boundary.governanceAnalyze).toHaveBeenCalledOnce()
  })

  it('lets a new clean finish after reset without an older completion clearing its busy state', async () => {
    const old = deferred<CleanPreviewResponse>()
    const current = deferred<CleanPreviewResponse>()
    boundary.cleanPreview.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    const view = await mount()
    await markMetadataModified(view.container)
    await click(view.container, 'DataGovernancePanel.tabs.clean.label')
    await click(view.container, 'DataCleaner.actions.apply')
    await click(view.container, 'DataGovernancePanel.actions.reset')
    await click(view.container, 'DataCleaner.actions.apply')
    expect(boundary.cleanPreview).toHaveBeenCalledTimes(2)

    await act(async () => old.resolve({ markdown: 'Stale', changed: true, applied_rules: 1 }))
    expect(button(view.container, 'DataCleaner.actions.applying').disabled).toBe(true)
    expect(view.container.querySelector('[data-displayed-content]')?.textContent).toBe(ORIGINAL)

    await act(async () => current.resolve({ markdown: 'Current', changed: true, applied_rules: 1 }))
    expect(view.container.querySelector('[data-displayed-content]')?.textContent).toBe('Current')
    expect(button(view.container, 'DataCleaner.actions.apply').disabled).toBe(false)
  })
})

describe('library synchronization', () => {
  it.each(['parsing', 'knowledge'] as const)('includes page two of the %s library', async (source) => {
    const request = source === 'parsing' ? boundary.listParsing : boundary.listKnowledge
    request.mockResolvedValueOnce({
      total: 201,
      items: Array.from({ length: 200 }, (_, i) => remoteDocument(`page-one-${i}`)),
    })
    request.mockResolvedValueOnce({ total: 201, items: [remoteDocument('page-two')] })
    const view = await mount()

    await waitForAssertion(() =>
      expect(useParsedFiles.getState().files.some((file) => file.id === 'page-two')).toBe(true),
    )
    expect(button(view.container, 'DataGovernancePanel.a11y.openFile {"filename":"page-two.md"}')).toBeDefined()
    expect(request.mock.calls.map(([params]) => params.skip)).toEqual([0, 200])
  })

  it('keeps known non-success lifecycle states out of the parsed bucket', async () => {
    const statuses = [
      'pending',
      'processing',
      'completed',
      'failed',
      'cancelled',
      'quarantined',
      'deleting',
      'future-state',
    ]
    boundary.listKnowledge.mockResolvedValue({
      total: 8,
      items: statuses.map((status) => ({ ...remoteDocument(status), status })),
    })
    await mount()

    await waitForAssertion(() => expect(useParsedFiles.getState().files).toHaveLength(9))
    expect(
      Object.fromEntries(
        useParsedFiles
          .getState()
          .files.filter((file) => file.source)
          .map((file) => [file.id, file.status]),
      ),
    ).toEqual({
      pending: 'pending',
      processing: 'parsing',
      completed: 'parsed',
      failed: 'error',
      cancelled: 'error',
      quarantined: 'error',
      deleting: 'pending',
      'future-state': 'pending',
    })
  })

  it('keeps a successful source when the other source fails', async () => {
    const failure = new Error('Parsing source unavailable')
    boundary.listParsing.mockRejectedValue(failure)
    boundary.listKnowledge.mockResolvedValue({ total: 1, items: [remoteDocument('available')] })
    const view = await mount()

    await waitForAssertion(() =>
      expect(useParsedFiles.getState().files.some((file) => file.id === 'available')).toBe(true),
    )
    expect(button(view.container, 'DataGovernancePanel.a11y.openFile {"filename":"available.md"}')).toBeDefined()
    expect(boundary.reportWarning).toHaveBeenCalledWith('Failed to sync parsing documents for governance:', failure)
  })

  it('stops pagination at an empty terminal page even when total was stale', async () => {
    boundary.listParsing.mockResolvedValueOnce({
      total: 201,
      items: Array.from({ length: 200 }, (_, i) => remoteDocument(`row-${i}`)),
    })
    boundary.listParsing.mockResolvedValue({ total: 201, items: [] })
    const view = await mount()

    await waitForAssertion(() => {
      expect(useParsedFiles.getState().files).toHaveLength(201)
      expect(view.client.isFetching()).toBe(0)
    })
    expect(useParsedFiles.getState().files).toHaveLength(201)
    expect(boundary.listParsing.mock.calls.map(([params]) => params.skip)).toEqual([0, 200])
  })

  it('does not start another page after the parent unmounts', async () => {
    const first = deferred<{ total: number; items: Document[] }>()
    boundary.listParsing.mockReturnValue(first.promise)
    const view = await mount()
    view.unmount()
    await act(async () =>
      first.resolve({ total: 201, items: Array.from({ length: 200 }, (_, i) => remoteDocument(`row-${i}`)) }),
    )

    expect(boundary.listParsing).toHaveBeenCalledOnce()
    expect(useParsedFiles.getState().files).toHaveLength(1)
  })

  it('deduplicates workspace documents and preserves local draft, folder and readiness fields', async () => {
    boundary.listParsing.mockResolvedValue({
      total: 1,
      items: [remoteDocument('workspace', { metadata: { workspace: 'parsing' } })],
    })
    boundary.listKnowledge.mockResolvedValue({
      total: 2,
      items: [
        remoteDocument('workspace', { metadata: { workspace: 'parsing' } }),
        remoteDocument('file-a', { status: 'processing', dataset_id: 'dataset-a' }),
      ],
    })
    await mount([
      localFile('file-a', {
        markdownContent: 'Local draft',
        folderId: 'folder-a',
        chunkStatus: 'ready',
        governanceStatus: 'ready',
      }),
    ])

    await waitForAssertion(() =>
      expect(useParsedFiles.getState().files.find((file) => file.id === 'file-a')?.source).toBe('knowledge_base'),
    )
    expect(useParsedFiles.getState().files).toHaveLength(2)
    expect(useParsedFiles.getState().files.find((file) => file.id === 'workspace')?.source).toBe('parsing_workspace')
    expect(useParsedFiles.getState().files.find((file) => file.id === 'file-a')).toMatchObject({
      markdownContent: 'Local draft',
      originalMarkdownContent: ORIGINAL,
      folderId: 'folder-a',
      chunkStatus: 'ready',
      governanceStatus: 'ready',
      status: 'parsing',
      datasetId: 'dataset-a',
    })
  })
})

describe('edit and save workflow', () => {
  it('preserves original text in the shared content cache when saving an edited file', async () => {
    const view = await mount([localFile('file-a', { markdownContent: 'Already edited draft' })])
    await click(view.container, 'DataGovernancePanel.actions.save')

    expect(useParsedFiles.getState().files[0]).toMatchObject({
      markdownContent: 'Already edited draft',
      originalMarkdownContent: ORIGINAL,
      chunkStatus: 'ready',
    })
    // Edit through the actual parent canvas before another save.
    await click(view.container, 'DataGovernancePanel.canvas.viewModes.edit')
    await type(view.container.querySelector('textarea')!, 'New saved draft')
    await click(view.container, 'DataGovernancePanel.actions.save')

    expect(boundary.saveContent).toHaveBeenLastCalledWith(
      { id: 'file-a', markdownContent: 'New saved draft', originalMarkdownContent: ORIGINAL },
      'tenant-a:user-a',
    )
  })

  it('filters the file list through the visible filename search', async () => {
    const view = await mount([localFile('alpha'), localFile('beta')])
    await type(view.container.querySelector<HTMLInputElement>('input[type="text"]')!, 'BETA')

    expect(view.container.querySelector("[aria-label*='alpha.md']")).toBeNull()
    expect(button(view.container, 'DataGovernancePanel.a11y.openFile {"filename":"beta.md"}')).toBeDefined()
  })

  it('saves the selected file, submits its checked ready entry and preserves the dataset route', async () => {
    boundary.search = 'tab=clean&dataset_id=dataset%2Fa'
    boundary.listDatasets.mockResolvedValue([{ id: 'dataset/a', name: 'Dataset A' }])
    const view = await mount([
      localFile('file-a', { datasetId: 'dataset/a' }),
      localFile('file-b', { datasetId: 'dataset-b' }),
    ])
    await click(view.container, 'DataCleaner.actions.apply')
    await click(view.container, 'DataGovernancePanel.actions.save')
    expect(useParsedFiles.getState().files[0]).toMatchObject({
      markdownContent: 'Cleaned content',
      originalMarkdownContent: ORIGINAL,
      chunkStatus: 'ready',
    })
    expect(view.container.querySelector("[aria-label*='file-b.md']")).toBeNull()
    expect(button(view.container, 'DataGovernancePanel.a11y.toggleChunkFile').getAttribute('aria-pressed')).toBe('true')

    await click(view.container, 'DataGovernancePanel.actions.submitSelectedToChunkPreview')

    expect(useParsedFiles.getState().files[0].chunkStatus).toBe('submitted')
    expect(useParsedFiles.getState().files[1].chunkStatus).toBeUndefined()
    expect(boundary.router.push).toHaveBeenCalledWith('/chunk-preview?dataset_id=dataset%2Fa')
    expect(boundary.listKnowledge).toHaveBeenCalledWith({ skip: 0, limit: 200, dataset_id: 'dataset/a' })
  })

  it('combines folder descendants and file selection without mixing equal-text drafts', async () => {
    const view = await mount([
      localFile('file-a', { folderId: 'parent' }),
      localFile('file-b', { folderId: 'child' }),
      localFile('outside'),
    ])
    await act(async () =>
      useParsedFiles.setState({
        folders: [
          { id: 'parent', name: 'Parent', parentId: ROOT_FOLDER_ID, createdAt: '2026-11-05' },
          { id: 'child', name: 'Child', parentId: 'parent', createdAt: '2026-11-05' },
        ],
        activeFolderId: 'parent',
      }),
    )
    expect(view.container.querySelector("[aria-label*='outside.md']")).toBeNull()
    await click(view.container, 'DataGovernancePanel.a11y.openFile {"filename":"file-b.md"}')
    await click(view.container, 'DataGovernancePanel.canvas.viewModes.edit')
    await type(view.container.querySelector('textarea')!, 'Only file B changed')
    await click(view.container, 'DataGovernancePanel.actions.save')

    expect(useParsedFiles.getState().files[0].markdownContent).toBe(ORIGINAL)
    expect(useParsedFiles.getState().files[1].markdownContent).toBe('Only file B changed')
  })
})

describe('upload and content boundaries', () => {
  it('adds preview segments through the existing upload contract', async () => {
    boundary.preview.mockResolvedValue({
      segments: [{ content: 'First' }, { content: 'Second' }],
      parser_backend: 'auto',
    })
    const view = await mount([])
    const file = new File(['source'], 'upload.md', { type: 'text/markdown' })
    await upload(view.container, [file])

    expect(useParsedFiles.getState().files).toHaveLength(1)
    expect(useParsedFiles.getState().files[0]).toMatchObject({
      filename: 'upload.md',
      markdownContent: 'First\n\nSecond',
      status: 'parsed',
    })
    expect(boundary.preview).toHaveBeenCalledWith(file, 'auto', undefined, {
      signal: expect.any(AbortSignal),
      dataset_id: undefined,
    })
  })

  it('discards a preview after cancelling the upload', async () => {
    const pending = deferred<{ segments: Array<{ content: string }>; parser_backend: string }>()
    boundary.preview.mockReturnValue(pending.promise)
    const view = await mount([])
    await upload(view.container, [new File(['source'], 'upload.md')])
    const signal = boundary.preview.mock.calls[0][3].signal as AbortSignal
    await click(view.container, 'DataGovernancePanel.emptyUpload.cancelParsing')
    expect(signal.aborted).toBe(true)
    await act(async () => pending.resolve({ segments: [{ content: 'Discarded' }], parser_backend: 'auto' }))

    expect(useParsedFiles.getState().files).toHaveLength(0)
    expect(boundary.success).not.toHaveBeenCalled()
  })

  it('does not create ZIP folders or publish success after upload cancellation', async () => {
    const pending = deferred<Array<{ file: File; path: string }>>()
    boundary.extractZip.mockReturnValue(pending.promise)
    const view = await mount([])
    await upload(view.container, [new File(['zip'], 'upload.zip')])
    await click(view.container, 'DataGovernancePanel.emptyUpload.cancelParsing')
    await act(async () =>
      pending.resolve([{ file: new File(['source'], 'upload.md'), path: 'Discarded folder/upload.md' }]),
    )

    expect(useParsedFiles.getState().folders).toHaveLength(0)
    expect(boundary.preview).not.toHaveBeenCalled()
    expect(boundary.success).not.toHaveBeenCalled()
  })

  it('loads cached text before trying a remote content request', async () => {
    boundary.cachedContent.mockResolvedValue({
      markdownContent: 'Cached draft',
      originalMarkdownContent: 'Cached original',
    })
    const view = await mount([
      localFile('file-a', { markdownContent: '', originalMarkdownContent: '', source: 'knowledge_base' }),
    ])

    await waitForAssertion(() =>
      expect(view.container.querySelector('[data-displayed-content]')?.textContent).toBe('Cached draft'),
    )
    expect(boundary.knowledgeContent).not.toHaveBeenCalled()
    expect(useParsedFiles.getState().files[0].originalMarkdownContent).toBe('Cached original')
  })

  it('loads knowledge content when the cache has no text', async () => {
    boundary.knowledgeContent.mockResolvedValue({
      markdown_content: 'Remote draft',
      original_markdown_content: 'Remote original',
    })
    const view = await mount([
      localFile('file-a', { markdownContent: '', originalMarkdownContent: '', source: 'knowledge_base' }),
    ])

    await waitForAssertion(() =>
      expect(view.container.querySelector('[data-displayed-content]')?.textContent).toBe('Remote draft'),
    )
    expect(boundary.knowledgeContent).toHaveBeenCalledWith('file-a', { max_chars: 2_000_000 })
    expect(useParsedFiles.getState().files[0].originalMarkdownContent).toBe('Remote original')
  })
})
