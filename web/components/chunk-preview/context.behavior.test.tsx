// @vitest-environment happy-dom

import React, { act, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { QueryProvider } from '@/components/providers/query-provider'
import { ParserBackendProvider } from '@/contexts/parser-backend-context'
import { ChunkStrategyProvider } from '@/contexts/chunk-strategy-context'
import { PipelineOptionsProvider, usePipelineOptions } from '@/contexts/pipeline-options-context'
import { useQueryClient } from '@tanstack/react-query'
import { waitForAssertion } from '@/test/hook-harness'
import { clearAuthSession, setAccessToken, setAuthSession } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import type { ParsedFileData } from '@/store/use-parsed-files-store'
import type { ChunkPreviewResponse } from '@/types'
import { ChunkAutoTuneDialog } from './components/chunk-auto-tune-dialog'
import { ChunkPresetPanel } from './components/chunk-preset-panel'
import { Sidebar } from './components/workbench/sidebar-client'
import { TopBar } from './components/workbench/top-bar'
import { ChunkList } from './components/workbench/preview/chunk-list'

const api = vi.hoisted(() => ({
  documents: {
    list: vi.fn(),
    getParsedContent: vi.fn(),
    chunkPreview: vi.fn(),
    chunkPreviewBySha: vi.fn(),
    createFromChunks: vi.fn(),
    getStatus: vi.fn(),
  },
  parsing: { listDocuments: vi.fn(), getContent: vi.fn() },
  presets: { list: vi.fn(), update: vi.fn(), create: vi.fn() },
  datasets: { list: vi.fn() },
  pipeline: {
    listPipelinePlugins: vi.fn(),
    ingestionPreview: vi.fn(),
    buildPluginChunkReport: vi.fn(),
    generateAndImportPluginGoldenDraft: vi.fn(),
  },
  evaluations: { createRegressionRun: vi.fn() },
  parsedFiles: [] as ParsedFileData[],
  capabilities: { capabilities: null, parserBackendAvailable: vi.fn(), chunkStrategyAvailable: vi.fn() },
  router: { replace: vi.fn() },
  search: new URLSearchParams(),
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), message: vi.fn() },
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api', () => ({
  documentApi: api.documents,
  parsingApi: api.parsing,
  chunkPresetApi: api.presets,
  datasetApi: api.datasets,
  pipelineApi: api.pipeline,
  evaluationApi: api.evaluations,
}))
vi.mock('@/contexts/pipeline-capabilities-context', () => ({ usePipelineCapabilities: () => api.capabilities }))
vi.mock('@/store/use-parsed-files-store', () => ({
  useParsedFiles: (select: (state: { files: ParsedFileData[] }) => unknown) => select({ files: api.parsedFiles }),
}))
vi.mock('next/navigation', () => ({ useSearchParams: () => api.search }))
vi.mock('@/i18n/navigation', () => ({ useRouter: () => api.router }))
vi.mock('sonner', () => ({ toast: api.toast }))
vi.mock('next-intl', () => {
  const translate = (key: string) => key
  return { useTranslations: () => translate }
})
vi.mock('@/components/ui/dialog', async () => {
  const React = await import('react')
  function Container({ children }: { children?: React.ReactNode }) {
    return React.createElement('div', null, children)
  }
  return {
    Dialog: ({ open, children }: { open: boolean; children?: React.ReactNode }) =>
      open ? React.createElement('div', { role: 'dialog' }, children) : null,
    DialogContent: Container,
    DialogHeader: Container,
    DialogTitle: Container,
    DialogDescription: Container,
    DialogFooter: Container,
  }
})
vi.mock('@/components/ui/select', async () => {
  const React = await import('react')
  function Container({ children }: { children?: React.ReactNode }) {
    return React.createElement(React.Fragment, null, children)
  }
  return {
    Select: ({
      children,
      value,
      onValueChange,
    }: {
      children?: React.ReactNode
      value?: string
      onValueChange?: (value: string) => void
    }) =>
      React.createElement(
        'select',
        { value, onChange: (event: React.ChangeEvent<HTMLSelectElement>) => onValueChange?.(event.target.value) },
        children,
      ),
    SelectContent: Container,
    SelectItem: ({ children, value }: { children?: React.ReactNode; value: string }) =>
      React.createElement('option', { value }, children),
    SelectTrigger: () => null,
    SelectValue: () => null,
  }
})
vi.mock('@/components/ui/dropdown-menu', async () => {
  const React = await import('react')
  function Container({ children }: { children?: React.ReactNode }) {
    return React.createElement('div', null, children)
  }
  function Item({
    children,
    onSelect,
    disabled,
  }: {
    children?: React.ReactNode
    onSelect?: () => void
    disabled?: boolean
  }) {
    return React.createElement('button', { onClick: onSelect, disabled }, children)
  }
  return {
    DropdownMenu: Container,
    DropdownMenuTrigger: Container,
    DropdownMenuContent: Container,
    DropdownMenuItem: Item,
    DropdownMenuSeparator: () => null,
    DropdownMenuCheckboxItem: Item,
  }
})
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({ index, key: index, start: index * 140, size: 140 })),
    getTotalSize: () => count * 140,
    measureElement: vi.fn(),
    scrollToIndex: vi.fn(),
  }),
}))
vi.mock('@/components/pipeline-options-panel', () => ({ PipelineOptionsPanel: () => null }))
vi.mock('@/components/business/chunk-strategy-dropdown', () => ({ ChunkStrategyDropdown: () => null }))
vi.mock('@/components/test-generation-dialog', () => ({ TestGenerationDialog: () => null }))
vi.mock('@/components/ui/safe-responsive-chart', () => ({ SafeResponsiveChart: () => null }))

import { ChunkPreviewProvider, useChunkPreview } from './context'

const cleanups: Array<() => void> = []

function session(id: string) {
  setAuthSession({
    user: {
      id,
      email: `${id}@example.test`,
      username: id,
      is_active: true,
      created_at: '2026-11-05T00:00:00Z',
      last_login_at: null,
    },
    token: { access_token: `${id}-token`, token_type: 'bearer', expires_in: 3600 },
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function preview(filename = 'first.md', content = 'first text'): ChunkPreviewResponse {
  return {
    filename,
    file_type: 'md',
    file_size: content.length,
    total_chunks: 1,
    total_characters: content.length,
    params: { chunk_size: 1000, chunk_overlap: 200 },
    chunks: [{ index: 0, content, length: content.length, tokens_est: 10, start_index: 0, end_index: content.length }],
    parser_backend: 'auto',
    chunk_strategy: 'langchain_recursive',
    original_text: content,
  }
}

function fileEntry(file: File): FileSystemFileEntry {
  return {
    isFile: true,
    isDirectory: false,
    file: (resolve: (value: File) => void) => resolve(file),
  } as FileSystemFileEntry
}

function directoryEntry(batches: FileSystemEntry[][]): FileSystemDirectoryEntry {
  let index = 0
  return {
    isFile: false,
    isDirectory: true,
    createReader: () => ({
      readEntries: (resolve: (value: FileSystemEntry[]) => void) => resolve(batches[index++] || []),
    }),
  } as FileSystemDirectoryEntry
}

function drop(entries: FileSystemEntry[]): React.DragEvent {
  return {
    preventDefault: vi.fn(),
    dataTransfer: { items: entries.map((entry) => ({ webkitGetAsEntry: () => entry })) },
  } as unknown as React.DragEvent
}

async function mount(
  options: {
    strict?: boolean
    autoPreview?: boolean
    onConfirm?: () => void
    waitForScope?: boolean
    children?: React.ReactNode
  } = {},
) {
  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryProvider>
        <ParserBackendProvider>
          <ChunkStrategyProvider>
            <PipelineOptionsProvider>
              <ChunkPreviewProvider onConfirm={options.onConfirm}>
                {children}
                {options.children}
              </ChunkPreviewProvider>
            </PipelineOptionsProvider>
          </ChunkStrategyProvider>
        </ParserBackendProvider>
      </QueryProvider>
    )
  }
  type Value = ReturnType<typeof useChunkPreview> & {
    queryClient: ReturnType<typeof useQueryClient>
    pipeline: ReturnType<typeof usePipelineOptions>
  }
  const result = React.createRef<Value>()
  function Probe() {
    const preview = useChunkPreview()
    const queryClient = useQueryClient()
    const pipeline = usePipelineOptions()
    React.useImperativeHandle(result, () => ({ ...preview, queryClient, pipeline }), [preview, queryClient, pipeline])
    return null
  }
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const content = (
    <Wrapper>
      <Probe />
    </Wrapper>
  )
  act(() => root.render(options.strict ? <StrictMode>{content}</StrictMode> : content))
  const hook = { result: result as { current: Value } }
  let mounted = true
  const unmount = () => {
    if (mounted) {
      mounted = false
      act(() => root.unmount())
      container.remove()
    }
  }
  const client = hook.result.current.queryClient
  cleanups.push(() => {
    unmount()
    client.clear()
  })
  if (options.waitForScope !== false) {
    await waitForAssertion(() => expect(hook.result.current.scopeSyncLoading).toBe(false))
  }
  act(() => hook.result.current.toggleAutoPreview(options.autoPreview ?? false))
  return { ...hook, unmount, container }
}

function click(hook: Awaited<ReturnType<typeof mount>>, text: string) {
  const button = Array.from(hook.container.querySelectorAll('button')).find(
    (button) => button.textContent?.trim() === text,
  )
  expect(button, `button ${text}`).toBeDefined()
  act(() => button!.click())
}

function changeText(input: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, value)
  act(() => input.dispatchEvent(new Event('input', { bubbles: true })))
}

function clipboard() {
  const previous = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
  const value = { readText: vi.fn(), writeText: vi.fn().mockResolvedValue(undefined) }
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value })
  cleanups.push(() => {
    if (previous) Object.defineProperty(navigator, 'clipboard', previous)
    else Reflect.deleteProperty(navigator, 'clipboard')
  })
  return value
}

async function preparePluginSidebar() {
  api.pipeline.listPipelinePlugins.mockResolvedValue({
    items: [
      {
        id: 'plugin-a',
        name: 'Plugin A',
        version: '1',
        executable: true,
        refs: { chunk: 'module:a' },
        contract: { golden: { enabled: true } },
      },
      {
        id: 'plugin-b',
        name: 'Plugin B',
        version: '1',
        executable: true,
        refs: { chunk: 'module:b' },
        contract: { golden: { enabled: true } },
      },
    ],
    errors: [],
  })
  const hook = await mount({ children: <Sidebar /> })
  await waitForAssertion(() => expect(hook.container.textContent).toContain('Plugin A'))
  act(() => {
    hook.result.current.setDatasetId('dataset-a')
    hook.result.current.pipeline.updateOption('chunk_python_plugin', 'module:a')
  })
  await waitForAssertion(() => expect(hook.result.current.scopeSyncLoading).toBe(false))
  return hook
}

async function prepareFile(hook: Awaited<ReturnType<typeof mount>>, name = 'first.md') {
  const file = new File(['first text'], name, { type: 'text/markdown' })
  act(() => hook.result.current.addFiles([file]))
  await act(async () => hook.result.current.runPreview())
  return file
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  clearAuthSession()
  session('user-a')
  vi.clearAllMocks()
  api.search = new URLSearchParams()
  api.parsedFiles = []
  api.capabilities.parserBackendAvailable.mockReturnValue(undefined)
  api.capabilities.chunkStrategyAvailable.mockReturnValue(undefined)
  api.documents.list.mockReset().mockResolvedValue({ items: [], total: 0 })
  api.documents.getParsedContent.mockReset().mockResolvedValue({ markdown_content: '' })
  api.parsing.listDocuments.mockReset().mockResolvedValue({ items: [], total: 0 })
  api.parsing.getContent.mockReset().mockResolvedValue({ markdown_content: '' })
  api.documents.chunkPreview.mockReset().mockImplementation(async (file: File) => preview(file.name))
  api.documents.chunkPreviewBySha.mockReset().mockResolvedValue(preview())
  api.documents.createFromChunks.mockReset().mockResolvedValue({ id: 'created-document', status: 'completed' })
  api.documents.getStatus.mockReset().mockResolvedValue({ status: 'completed' })
  api.presets.list.mockReset().mockResolvedValue({ items: [] })
  api.presets.update.mockReset().mockResolvedValue({})
  api.presets.create.mockReset().mockResolvedValue({ id: 'created-preset' })
  api.datasets.list.mockReset().mockResolvedValue({ items: [] })
  api.pipeline.listPipelinePlugins.mockReset().mockResolvedValue({ items: [], errors: [] })
  api.pipeline.ingestionPreview.mockReset()
  api.pipeline.buildPluginChunkReport.mockReset()
  api.pipeline.generateAndImportPluginGoldenDraft.mockReset()
  api.evaluations.createRegressionRun.mockReset()
})

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) cleanup()
  await act(async () => {
    await Promise.resolve()
  })
  vi.restoreAllMocks()
  document.body.replaceChildren()
})

describe('chunk preview workspace state and request lifetime', () => {
  it('restores a saved focus after the backend fills an incomplete parsed-file cache', async () => {
    const response = deferred<{
      items: Array<{ id: string; filename: string; file_type: string; file_size: number }>
      total: number
    }>()
    localStorage.setItem('mimirq_chunk_preview_focus_file_id', 'doc-b')
    api.parsedFiles = [
      {
        id: 'doc-a',
        filename: 'a.md',
        fileType: 'md',
        fileSize: 6,
        markdownContent: 'cached',
        parsedAt: '2026-11-05T00:00:00Z',
        parser: 'auto',
        source: 'parsing_workspace',
      },
    ]
    api.parsing.listDocuments.mockReturnValue(response.promise)
    api.parsing.getContent.mockImplementation(async (id: string) => ({ markdown_content: id }))
    const hook = await mount({ waitForScope: false })
    expect(hook.result.current.fileList.map((item) => item.id)).toEqual(['doc-a'])

    await act(async () =>
      response.resolve({
        items: [
          { id: 'doc-a', filename: 'a.md', file_type: 'md', file_size: 6 },
          { id: 'doc-b', filename: 'b.md', file_type: 'md', file_size: 6 },
        ],
        total: 2,
      }),
    )

    expect(hook.result.current.currentFileItem?.id).toBe('doc-b')
  })

  it('marks a legitimate new-session preview clean after the same user logs in again', async () => {
    const hook = await mount()
    await prepareFile(hook)
    act(() => session('user-a'))

    await act(async () => hook.result.current.runPreview({ force: true }))

    expect(hook.result.current.isPreviewDirty).toBe(false)
  })

  it('restores the saved dataset in StrictMode before persisting it', async () => {
    localStorage.setItem('mimirq_chunk_preview_dataset_id', 'dataset-a')
    const hook = await mount({ strict: true })

    expect(hook.result.current.datasetId).toBe('dataset-a')
    expect(localStorage.getItem('mimirq_chunk_preview_dataset_id')).toBe('dataset-a')
  })

  it('retires a running tune when the parser selection changes', async () => {
    const response = deferred<ChunkPreviewResponse>()
    api.documents.chunkPreview.mockResolvedValue({ ...preview(), file_sha256: 'first-sha' })
    api.documents.chunkPreviewBySha.mockReturnValue(response.promise)
    const hook = await mount({ children: <ChunkAutoTuneDialog /> })
    await prepareFile(hook)
    click(hook, 'autoTune.trigger.label')
    click(hook, 'autoTune.actions.start')
    act(() => hook.result.current.setParserBackend('marker'))

    await act(async () => response.resolve(preview()))

    expect(api.documents.chunkPreviewBySha).toHaveBeenCalledOnce()
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it('ignores a scoped content response after the same user explicitly logs in again', async () => {
    const response = deferred<{ markdown_content: string }>()
    api.parsing.listDocuments.mockResolvedValue({
      items: [{ id: 'old-doc', filename: 'old.md', file_type: 'md', file_size: 10 }],
      total: 1,
    })
    api.parsing.getContent.mockReturnValue(response.promise)
    const hook = await mount({ waitForScope: false })
    await waitForAssertion(() => expect(api.parsing.getContent).toHaveBeenCalledOnce())
    act(() => session('user-a'))

    await act(async () => response.resolve({ markdown_content: 'old session content' }))

    expect(hook.result.current.fileList).toEqual([])
  })

  it('keeps an ordinary access-token refresh eligible for its pending preview', async () => {
    const response = deferred<ChunkPreviewResponse>()
    api.documents.chunkPreview.mockReturnValue(response.promise)
    const hook = await mount()
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md')]))
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.runPreview()
    })
    act(() => setAccessToken({ access_token: 'refreshed-token', token_type: 'bearer', expires_in: 3600 }))

    await act(async () => {
      response.resolve(preview())
      await completion
    })

    expect(hook.result.current.previewData?.filename).toBe('first.md')
  })

  it('retires a pending network preview when the user restores its cached result', async () => {
    const hook = await mount()
    await prepareFile(hook)
    const response = deferred<ChunkPreviewResponse>()
    api.documents.chunkPreview.mockReturnValue(response.promise)
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.runPreview({ force: true })
    })
    await act(async () => hook.result.current.runPreview())

    await act(async () => {
      response.resolve(preview('first.md', 'late changed text'))
      await completion
    })

    expect(hook.result.current.previewData?.chunks[0].content).toBe('first text')
    expect(hook.result.current.cacheHit).toBe(true)
    expect(hook.result.current.isLoading).toBe(false)
  })

  it('keeps a same-session scoped load deduplicated through StrictMode effect replay', async () => {
    const hook = await mount({ strict: true })

    expect(hook.result.current.scopeSyncLoading).toBe(false)
    expect(api.parsing.listDocuments).toHaveBeenCalledOnce()
  })

  it('locks batch and single ingestion together while preserving each file queue completion', async () => {
    const response = deferred<{ id: string; status: string }>()
    const hook = await mount()
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md'), new File(['second'], 'second.md')]))
    await act(async () => hook.result.current.runPreview())
    const ids = hook.result.current.fileList.map((item) => item.id)
    act(() => ids.forEach((id) => hook.result.current.toggleIngestFileSelection(id)))
    api.documents.createFromChunks
      .mockReturnValueOnce(response.promise)
      .mockResolvedValue({ id: 'created-second', status: 'completed' })
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.submitSelectedFiles()
      void hook.result.current.submitChunks()
    })
    expect(api.documents.createFromChunks).toHaveBeenCalledOnce()
    act(() => hook.result.current.setCurrentFileIndex(1))

    await act(async () => {
      response.resolve({ id: 'created-first', status: 'completed' })
      await completion
    })

    expect(api.documents.createFromChunks).toHaveBeenCalledTimes(2)
    expect(hook.result.current.processedStatus).toMatchObject({ [ids[0]]: 'success', [ids[1]]: 'success' })
    expect(hook.result.current.createdDocumentId).toBeNull()
    expect(hook.result.current.submitSuccess).toBe(false)
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it('does not submit an old batch preview after a replacement login', async () => {
    const response = deferred<ChunkPreviewResponse>()
    const hook = await mount()
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md')]))
    act(() => hook.result.current.toggleIngestFileSelection(hook.result.current.currentFileItem!.id))
    api.documents.chunkPreview.mockReturnValue(response.promise)
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.submitSelectedFiles()
    })
    act(() => session('user-a'))

    await act(async () => {
      response.resolve(preview())
      await completion
    })

    expect(api.documents.createFromChunks).not.toHaveBeenCalled()
  })

  it('does not create an old golden regression after the login session was replaced', async () => {
    const response = deferred<{
      draft: { items_total: number }
      import_result: { case_ids: string[]; created: number; updated: number; skipped: number }
    }>()
    api.pipeline.generateAndImportPluginGoldenDraft.mockReturnValue(response.promise)
    const hook = await preparePluginSidebar()
    click(hook, 'sidebar.pythonPlugins.importAndRunGolden')
    act(() => session('user-a'))

    await act(async () =>
      response.resolve({
        draft: { items_total: 1 },
        import_result: { case_ids: ['case-a'], created: 1, updated: 0, skipped: 0 },
      }),
    )

    expect(api.evaluations.createRegressionRun).not.toHaveBeenCalled()
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it('finishes an accepted golden import and regression against original caches after unmount', async () => {
    const response = deferred<{
      draft: { items_total: number }
      import_result: { case_ids: string[]; created: number; updated: number; skipped: number }
    }>()
    api.pipeline.generateAndImportPluginGoldenDraft.mockReturnValue(response.promise)
    api.evaluations.createRegressionRun.mockResolvedValue({ id: 'run-a' })
    const hook = await preparePluginSidebar()
    const client = hook.result.current.queryClient
    const key = queryKeys.evaluations.regressionRuns({ dataset_id: 'dataset-a', limit: 50 })
    const unrelated = queryKeys.evaluations.regressionRuns({ dataset_id: 'dataset-b', limit: 50 })
    client.setQueryData(key, { items: [], total: 0 })
    client.setQueryData(unrelated, { items: [], total: 0 })
    click(hook, 'sidebar.pythonPlugins.importAndRunGolden')
    hook.unmount()

    await act(async () =>
      response.resolve({
        draft: { items_total: 1 },
        import_result: { case_ids: ['case-a'], created: 1, updated: 0, skipped: 0 },
      }),
    )

    expect(api.evaluations.createRegressionRun).toHaveBeenCalledWith(
      expect.objectContaining({ dataset_id: 'dataset-a', case_ids: ['case-a'] }),
    )
    expect(client.getQueryState(key)?.isInvalidated).toBe(true)
    expect(client.getQueryState(unrelated)?.isInvalidated).toBe(false)
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it('imports a current clipboard config, preserving number coercion and separator overlap policy', async () => {
    clipboard().readText.mockResolvedValue(
      JSON.stringify({
        dataset_id: '',
        parser_backend: 'marker',
        chunk_strategy: 'separator',
        chunk_size: '600',
        chunk_overlap: '90',
        separator: String.raw`\t`,
        keep_separator: false,
      }),
    )
    const hook = await mount({ children: <TopBar /> })
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md')]))

    click(hook, 'topBar.actions.importConfigFromClipboard')
    await waitForAssertion(() => expect(api.toast.success).toHaveBeenCalledWith('topBar.toasts.importedFromClipboard'))

    expect(hook.result.current).toMatchObject({
      parserBackend: 'marker',
      chunkStrategy: 'separator',
      chunkSize: 600,
      chunkOverlap: 0,
      separatorCustom: String.raw`\t`,
      keepSeparator: false,
    })
  })

  it('discards a plugin report after selecting a different plugin', async () => {
    const response = deferred<{
      passed: boolean
      sections: Array<{ knowledge_section: string; chunks: number }>
      summary: {}
    }>()
    api.pipeline.buildPluginChunkReport.mockReturnValue(response.promise)
    const hook = await preparePluginSidebar()
    click(hook, 'sidebar.pythonPlugins.chunkReportBuild')
    act(() => hook.result.current.pipeline.updateOption('chunk_python_plugin', 'module:b'))

    await act(async () =>
      response.resolve({
        passed: true,
        summary: {},
        sections: [{ knowledge_section: 'private-a-section', chunks: 1 }],
      }),
    )

    expect(hook.container.textContent).not.toContain('private-a-section')
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it('locks golden import and regression as one synchronous submission', async () => {
    const response = deferred<{
      draft: { items_total: number }
      import_result: { case_ids: string[]; created: number; updated: number; skipped: number }
    }>()
    api.pipeline.generateAndImportPluginGoldenDraft.mockReturnValue(response.promise)
    const hook = await preparePluginSidebar()
    const button = Array.from(hook.container.querySelectorAll('button')).find(
      (button) => button.textContent === 'sidebar.pythonPlugins.importGolden',
    )!

    act(() => {
      button.click()
      button.click()
    })

    expect(api.pipeline.generateAndImportPluginGoldenDraft).toHaveBeenCalledOnce()
    await act(async () =>
      response.resolve({
        draft: { items_total: 1 },
        import_result: { case_ids: ['case-a'], created: 1, updated: 0, skipped: 0 },
      }),
    )
  })

  it('completes original golden cache work after unmount while suppressing view publication', async () => {
    const response = deferred<{
      draft: { items_total: number }
      import_result: { case_ids: string[]; created: number; updated: number; skipped: number }
    }>()
    api.pipeline.generateAndImportPluginGoldenDraft.mockReturnValue(response.promise)
    const hook = await preparePluginSidebar()
    const client = hook.result.current.queryClient
    const original = queryKeys.evaluations.regressionCases({ dataset_id: 'dataset-a', limit: 50 })
    const unrelated = queryKeys.evaluations.regressionCases({ dataset_id: 'dataset-b', limit: 50 })
    client.setQueryData(original, { items: [], total: 0 })
    client.setQueryData(unrelated, { items: [], total: 0 })
    click(hook, 'sidebar.pythonPlugins.importGolden')
    hook.unmount()

    await act(async () =>
      response.resolve({
        draft: { items_total: 1 },
        import_result: { case_ids: ['case-a'], created: 1, updated: 0, skipped: 0 },
      }),
    )

    expect(client.getQueryState(original)?.isInvalidated).toBe(true)
    expect(client.getQueryState(unrelated)?.isInvalidated).toBe(false)
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it('preserves a newer preset draft when an older create completes', async () => {
    const response = deferred<{ id: string }>()
    api.presets.create.mockReturnValue(response.promise)
    const hook = await mount({ children: <ChunkPresetPanel /> })
    click(hook, 'chunkPresetPanel.savePreset')
    const input = hook.container.querySelector<HTMLInputElement>(
      'input[placeholder="chunkPresetPanel.namePlaceholder"]',
    )!
    changeText(input, 'First draft')
    click(hook, 'save')
    changeText(input, 'Next draft')

    await act(async () => response.resolve({ id: 'created-first' }))

    expect(
      hook.container.querySelector<HTMLInputElement>('input[placeholder="chunkPresetPanel.namePlaceholder"]')?.value,
    ).toBe('Next draft')
    expect(hook.container.querySelector('select')?.value).toBe('__none__')
  })

  it('escapes an apostrophe in the copied cURL separator argument', async () => {
    const output = clipboard()
    const hook = await mount({ children: <TopBar /> })
    act(() => {
      hook.result.current.addFiles([new File(['first'], 'first.md')])
      hook.result.current.updateSettings({ strategy: 'separator' })
      hook.result.current.updateSeparatorSettings({ separatorPreset: 'custom', separatorCustom: "a'b" })
    })

    click(hook, 'topBar.actions.copyCurl')

    expect(output.writeText.mock.calls[0][0]).toContain(String.raw`separator=a\'b`)
  })

  it('preserves the backend token estimate when approving a chunk without changing its content', async () => {
    const data = preview()
    data.params.unit = 'tokens'
    data.chunks[0] = { ...data.chunks[0], tokens_est: 321, metadata: { needs_review: true } }
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    await waitForAssertion(() => expect(hook.container.textContent).toContain('321 token'))
    const approve = hook.container.querySelector<HTMLButtonElement>('[aria-label="chunkCard.approveReview"]')!

    act(() => approve.click())

    expect(hook.result.current.chunkOverrides[0].metadata?.review_status).toBe('approved')
    expect(hook.container.textContent).toContain('321 token')
  })

  it('recalculates the displayed token estimate for an actual content edit', async () => {
    const data = preview()
    data.params.unit = 'tokens'
    data.chunks[0].tokens_est = 321
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    act(() => hook.result.current.updateChunkOverride(0, { content: 'new text for display' }))

    expect(hook.container.textContent).not.toContain('321 token')
    expect(hook.container.textContent).toContain('new text for display')
  })

  it('restores all four history request settings before the history preview', async () => {
    const hook = await mount({ children: <Sidebar /> })
    act(() => {
      hook.result.current.setParserBackend('marker')
      hook.result.current.updateSettings({ chunkSize: 600, chunkOverlap: 60, strategy: 'langchain_token' })
    })
    await prepareFile(hook)
    act(() => {
      hook.result.current.setParserBackend('auto')
      hook.result.current.updateSettings({ chunkSize: 1200, chunkOverlap: 240, strategy: 'langchain_recursive' })
    })
    const history = Array.from(hook.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('sidebar.history.chunks'),
    )!

    await act(async () => history.click())

    expect(api.documents.chunkPreview.mock.lastCall?.[1]).toMatchObject({
      parser_backend: 'marker',
      chunk_strategy: 'langchain_token',
      chunk_size: 600,
      chunk_overlap: 60,
    })
  })

  it('does not show an old ingestion audit after switching its file', async () => {
    const response = deferred<never>()
    api.pipeline.ingestionPreview.mockReturnValue(response.promise)
    const hook = await mount({ children: <Sidebar /> })
    act(() => hook.result.current.setDatasetId('dataset-a'))
    await waitForAssertion(() => expect(hook.result.current.scopeSyncLoading).toBe(false))
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md'), new File(['second'], 'second.md')]))
    click(hook, 'sidebar.ingestionPreview.trigger')
    act(() => hook.result.current.setCurrentFileIndex(1))

    await act(async () => response.reject(new Error('private audit failure from first.md')))

    expect(hook.container.textContent).not.toContain('private audit failure from first.md')
  })

  it('does not import an old clipboard configuration after changing the selected file', async () => {
    const response = deferred<string>()
    clipboard().readText.mockReturnValue(response.promise)
    const hook = await mount({ children: <TopBar /> })
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md'), new File(['second'], 'second.md')]))
    click(hook, 'topBar.actions.importConfigFromClipboard')
    act(() => hook.result.current.setCurrentFileIndex(1))

    await act(async () => response.resolve(JSON.stringify({ chunk_size: 321 })))

    expect(hook.result.current.chunkSize).toBe(1000)
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it('does not import an old configuration file after changing the selected file', async () => {
    const response = deferred<string>()
    const config = new File(['{}'], 'config.json', { type: 'application/json' })
    Object.defineProperty(config, 'text', { value: () => response.promise })
    const hook = await mount({ children: <TopBar /> })
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md'), new File(['second'], 'second.md')]))
    const input = hook.container.querySelector<HTMLInputElement>('input[type="file"]')!
    Object.defineProperty(input, 'files', { configurable: true, value: [config] })
    act(() => input.dispatchEvent(new Event('change', { bubbles: true })))
    act(() => hook.result.current.setCurrentFileIndex(1))

    await act(async () => response.resolve(JSON.stringify({ chunk_size: 321 })))

    expect(hook.result.current.chunkSize).toBe(1000)
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it('copies a cURL with one continuation per intermediate line, including dataset and separator fields', async () => {
    const output = clipboard()
    const hook = await mount({ children: <TopBar /> })
    act(() => hook.result.current.setDatasetId('dataset-a'))
    await waitForAssertion(() => expect(hook.result.current.scopeSyncLoading).toBe(false))
    act(() => {
      hook.result.current.addFiles([new File(['first'], 'first.md')])
      hook.result.current.updateSettings({ strategy: 'separator' })
      hook.result.current.updateSeparatorSettings({ separatorPreset: 'custom', separatorCustom: "a'b" })
    })

    click(hook, 'topBar.actions.copyCurl')

    const text = output.writeText.mock.calls[0][0] as string
    const lines = text.split('\n')
    expect(lines.slice(0, -1).every((line) => line.endsWith(' \\') && !line.endsWith(' \\\\'))).toBe(true)
    expect(text).toContain(String.raw`separator=a\'b`)
  })

  it('keeps the latest dataset preset list when an earlier list resolves last', async () => {
    const response = deferred<{ items: Array<{ id: string; name: string }> }>()
    api.presets.list
      .mockReturnValueOnce(response.promise)
      .mockResolvedValue({ items: [{ id: 'preset-b', name: 'Preset B' }] })
    const hook = await mount({ children: <ChunkPresetPanel /> })
    act(() => hook.result.current.setDatasetId('dataset-b'))
    await waitForAssertion(() => expect(hook.container.textContent).toContain('Preset B'))

    await act(async () => response.resolve({ items: [{ id: 'preset-a', name: 'Private A' }] }))

    expect(hook.container.textContent).toContain('Preset B')
    expect(hook.container.textContent).not.toContain('Private A')
  })

  it('submits one preset create when the save control receives two synchronous clicks', async () => {
    const response = deferred<{ id: string }>()
    api.presets.create.mockReturnValue(response.promise)
    const hook = await mount({ children: <ChunkPresetPanel /> })
    click(hook, 'chunkPresetPanel.savePreset')
    const name = hook.container.querySelector<HTMLInputElement>(
      'input[placeholder="chunkPresetPanel.namePlaceholder"]',
    )!
    changeText(name, 'My preset')
    const save = Array.from(hook.container.querySelectorAll('button')).find((button) => button.textContent === 'save')!

    act(() => {
      save.click()
      save.click()
    })

    expect(api.presets.create).toHaveBeenCalledOnce()
    await act(async () => response.resolve({ id: 'created' }))
  })

  it('previews the chosen auto-tune recommendation with its new settings', async () => {
    const withSha = { ...preview(), file_sha256: 'first-sha' }
    api.documents.chunkPreview.mockResolvedValue(withSha)
    api.documents.chunkPreviewBySha.mockResolvedValue({
      ...withSha,
      stats: { count: 1, avg: 10, p90: 10, short_count: 0, coverage_ratio: 1, overlap_waste_ratio: 0 },
    })
    const hook = await mount({ children: <ChunkAutoTuneDialog /> })
    await prepareFile(hook)
    click(hook, 'autoTune.trigger.label')
    click(hook, 'autoTune.actions.start')
    await waitForAssertion(() => expect(hook.container.textContent).toContain('autoTune.actions.applyAndPreview'))
    const apply = Array.from(hook.container.querySelectorAll('button')).find(
      (button) => button.textContent?.trim() === 'autoTune.actions.applyAndPreview',
    )!

    await act(async () => apply.click())

    expect(hook.result.current.chunkSize).toBe(600)
    expect(api.documents.chunkPreviewBySha.mock.lastCall?.[0]).toMatchObject({ chunk_size: 600, chunk_overlap: 60 })
  })

  it('retires auto-tune results and follow-up requests when selecting another file', async () => {
    const response = deferred<ChunkPreviewResponse>()
    api.documents.chunkPreview.mockResolvedValue({ ...preview(), file_sha256: 'first-sha' })
    api.documents.chunkPreviewBySha.mockReturnValue(response.promise)
    const hook = await mount({ children: <ChunkAutoTuneDialog /> })
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md'), new File(['second'], 'second.md')]))
    await act(async () => hook.result.current.runPreview())
    click(hook, 'autoTune.trigger.label')
    click(hook, 'autoTune.actions.start')
    await waitForAssertion(() => expect(api.documents.chunkPreviewBySha).toHaveBeenCalledOnce())
    act(() => hook.result.current.setCurrentFileIndex(1))

    await act(async () => response.resolve(preview()))

    expect(api.documents.chunkPreviewBySha).toHaveBeenCalledOnce()
    expect(api.toast.success).not.toHaveBeenCalled()
    expect(hook.container.textContent).not.toContain('autoTune.actions.applyAndPreview')
  })

  it('drops every directory batch, including nested directory batches', async () => {
    const hook = await mount()
    const files = ['first.md', 'nested-first.md', 'nested-second.md', 'last.md'].map((name) => new File([name], name))
    const nested = directoryEntry([[fileEntry(files[1])], [fileEntry(files[2])], []])
    const directory = directoryEntry([[fileEntry(files[0]), nested], [fileEntry(files[3])], []])

    await act(async () => hook.result.current.handleDrop(drop([directory])))

    expect(hook.result.current.fileList.map((item) => item.file)).toEqual(files)
  })

  it('retains scanner errors instead of committing a partially scanned drop', async () => {
    const hook = await mount()
    const error = new DOMException('directory unavailable', 'NotReadableError')
    const failed = {
      isFile: true,
      isDirectory: false,
      file: (_: unknown, reject: (error: Error) => void) => reject(error),
    } as FileSystemFileEntry

    await expect(
      hook.result.current.handleDrop(drop([fileEntry(new File(['first'], 'first.md')), failed])),
    ).rejects.toBe(error)

    expect(hook.result.current.fileList).toEqual([])
  })

  it('does not append a pending directory drop to a replacement dataset', async () => {
    const hook = await mount()
    let finish!: (file: File) => void
    const pending = {
      isFile: true,
      isDirectory: false,
      file: (resolve: (file: File) => void) => {
        finish = resolve
      },
    } as FileSystemFileEntry
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.handleDrop(drop([pending]))
    })
    act(() => hook.result.current.setDatasetId('dataset-b'))

    await act(async () => {
      finish(new File(['old private'], 'old.md'))
      await completion
    })

    expect(hook.result.current.fileList).toEqual([])
  })

  it.each([false, true])('restores stored preview settings with StrictMode=%s', async (strict) => {
    const separator = {
      separatorPreset: 'custom',
      separatorCustom: String.raw`\t`,
      keepSeparator: false,
      separatorMaxChunkSize: 876,
    }
    const parentChild = { parentChildRatio: 0.75, parentChildMinChildSize: 350 }
    const perf = { includeOriginalText: false, originalTextMaxChars: 321, maxChunks: 77, useParseCache: false }
    localStorage.setItem('mimirq_chunk_preview_separator_settings', JSON.stringify(separator))
    localStorage.setItem('mimirq_chunk_preview_parent_child_settings', JSON.stringify(parentChild))
    localStorage.setItem('mimirq_chunk_preview_perf_settings', JSON.stringify(perf))

    const hook = await mount({ strict })

    expect(hook.result.current).toMatchObject({ ...separator, ...parentChild, ...perf })
    expect(JSON.parse(localStorage.getItem('mimirq_chunk_preview_separator_settings') || '{}')).toEqual(separator)
    expect(JSON.parse(localStorage.getItem('mimirq_chunk_preview_parent_child_settings') || '{}')).toEqual(parentChild)
    expect(JSON.parse(localStorage.getItem('mimirq_chunk_preview_perf_settings') || '{}')).toEqual(perf)
  })

  it('restores the focused document after scoped documents finish loading', async () => {
    localStorage.setItem('mimirq_chunk_preview_focus_file_id', 'doc-b')
    api.parsing.listDocuments.mockResolvedValue({
      items: [
        { id: 'doc-a', filename: 'a.md', file_type: 'md', file_size: 10 },
        { id: 'doc-b', filename: 'b.md', file_type: 'md', file_size: 10 },
      ],
      total: 2,
    })
    api.parsing.getContent.mockImplementation(async (id: string) => ({ markdown_content: `${id} content` }))

    const hook = await mount()

    await waitForAssertion(() => expect(hook.result.current.fileList).toHaveLength(2))
    expect(hook.result.current.currentFileItem?.id).toBe('doc-b')
  })

  it('does not publish a preview response that completes after cancel', async () => {
    const response = deferred<ChunkPreviewResponse>()
    api.documents.chunkPreview.mockReturnValue(response.promise)
    const hook = await mount()
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md', { type: 'text/markdown' })]))
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.runPreview()
    })
    act(() => hook.result.current.cancelPreview())

    await act(async () => {
      response.resolve(preview())
      await completion
    })

    expect(hook.result.current.previewData).toBeNull()
    expect(hook.result.current.runHistory).toEqual([])
    expect(hook.result.current.isLoading).toBe(false)
  })

  it('keeps an automatic preview canceled until another user action', async () => {
    const response = deferred<ChunkPreviewResponse>()
    api.documents.chunkPreview.mockReturnValue(response.promise)
    const hook = await mount({ autoPreview: true })
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md')]))
    await waitForAssertion(() => expect(api.documents.chunkPreview).toHaveBeenCalledOnce())
    act(() => hook.result.current.cancelPreview())

    await act(async () => response.resolve(preview()))

    expect(api.documents.chunkPreview).toHaveBeenCalledOnce()
    expect(hook.result.current.autoPreviewEnabled).toBe(true)
    expect(hook.result.current.isLoading).toBe(false)
    expect(hook.result.current.previewData).toBeNull()
  })

  it.each(['clearFiles', 'reset'] as const)('does not revive a preview after %s', async (action) => {
    const response = deferred<ChunkPreviewResponse>()
    api.documents.chunkPreview.mockReturnValue(response.promise)
    const hook = await mount()
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md')]))
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.runPreview()
    })
    act(() => hook.result.current[action]())

    await act(async () => {
      response.resolve(preview())
      await completion
    })

    expect(hook.result.current.fileList).toEqual([])
    expect(hook.result.current.previewData).toBeNull()
    expect(hook.result.current.runHistory).toEqual([])
    expect(hook.result.current.isLoading).toBe(false)
  })

  it('does not publish the previous file after switching the file being previewed', async () => {
    const response = deferred<ChunkPreviewResponse>()
    api.documents.chunkPreview.mockReturnValueOnce(response.promise)
    const hook = await mount()
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md'), new File(['second'], 'second.md')]))
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.runPreview()
    })
    act(() => hook.result.current.setCurrentFileIndex(1))

    await act(async () => {
      response.resolve(preview('first.md'))
      await completion
    })

    expect(hook.result.current.currentFile?.name).toBe('second.md')
    expect(hook.result.current.previewData).toBeNull()
    await act(async () => hook.result.current.runPreview())
    expect(hook.result.current.previewData?.filename).toBe('second.md')
  })

  it('keeps distinct files separate when their names, sizes and modification times match', async () => {
    const first = new File(['aaaa'], 'same.md', { lastModified: 1700000000000 })
    const second = new File(['bbbb'], 'same.md', { lastModified: 1700000000000 })
    api.documents.chunkPreview.mockImplementation(async (file: File) =>
      preview(file.name, file === first ? 'aaaa' : 'bbbb'),
    )
    const hook = await mount()
    act(() => hook.result.current.addFiles([first, second]))
    await act(async () => hook.result.current.runPreview())
    act(() => hook.result.current.setCurrentFileIndex(1))

    await act(async () => hook.result.current.runPreview())

    expect(hook.result.current.previewData?.chunks[0].content).toBe('bbbb')
    expect(api.documents.chunkPreview).toHaveBeenCalledTimes(2)
  })

  it('reuses a valid preview for the same file and settings', async () => {
    const hook = await mount()
    await prepareFile(hook)

    await act(async () => hook.result.current.runPreview())

    expect(api.documents.chunkPreview).toHaveBeenCalledOnce()
    expect(hook.result.current.cacheHit).toBe(true)
  })

  it('does not clear another file preview or edit when removing an inactive file', async () => {
    const hook = await mount()
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md'), new File(['second'], 'second.md')]))
    act(() => hook.result.current.setCurrentFileIndex(1))
    await act(async () => hook.result.current.runPreview())
    act(() => hook.result.current.updateChunkOverride(0, { content: 'second-file draft' }))
    const currentPreview = hook.result.current.previewData

    act(() => hook.result.current.removeFile(0))

    expect(hook.result.current.currentFile?.name).toBe('second.md')
    expect(hook.result.current.previewData).toBe(currentPreview)
    expect(hook.result.current.chunkOverrides[0]?.content).toBe('second-file draft')
  })

  it('accepts only one Ctrl+S submission while its backend request is pending', async () => {
    const response = deferred<{ id: string; status: string }>()
    const hook = await mount()
    await prepareFile(hook)
    api.documents.createFromChunks.mockReturnValue(response.promise)

    try {
      act(() => {
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 's', ctrlKey: true }))
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 's', ctrlKey: true }))
      })

      expect(api.documents.createFromChunks).toHaveBeenCalledOnce()
    } finally {
      await act(async () => {
        response.resolve({ id: 'created-document', status: 'completed' })
        await response.promise
      })
    }
  })

  it('keeps the new file view unchanged when a previous file finishes ingesting', async () => {
    const response = deferred<{ id: string; status: string }>()
    const hook = await mount()
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md'), new File(['second'], 'second.md')]))
    await act(async () => hook.result.current.runPreview())
    const firstId = hook.result.current.currentFileItem!.id
    api.documents.createFromChunks.mockReturnValue(response.promise)
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.submitChunks()
    })
    act(() => hook.result.current.setCurrentFileIndex(1))

    await act(async () => {
      response.resolve({ id: 'created-first', status: 'completed' })
      await completion
    })

    expect(hook.result.current.currentFile?.name).toBe('second.md')
    expect(hook.result.current.createdDocumentId).toBeNull()
    expect(hook.result.current.submitSuccess).toBe(false)
    expect(hook.result.current.processedStatus[firstId]).toBe('success')
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it('refreshes valid original document lists after an accepted write outlives its view', async () => {
    const response = deferred<{ id: string; status: string }>()
    const onConfirm = vi.fn()
    const hook = await mount({ onConfirm })
    act(() => hook.result.current.setDatasetId('dataset-a'))
    await waitForAssertion(() => expect(hook.result.current.scopeSyncLoading).toBe(false))
    await prepareFile(hook)
    const client = hook.result.current.queryClient
    const originalKey = queryKeys.documents.list({ dataset_id: 'dataset-a', limit: 100 })
    const unrelatedKey = queryKeys.documents.list({ dataset_id: 'dataset-b', limit: 100 })
    client.setQueryData(originalKey, { items: [], total: 0 })
    client.setQueryData(unrelatedKey, { items: [], total: 0 })
    api.documents.createFromChunks.mockReturnValue(response.promise)
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.submitChunks()
    })
    hook.unmount()

    await act(async () => {
      response.resolve({ id: 'created-document', status: 'completed' })
      await completion
    })

    expect(client.getQueryState(originalKey)?.isInvalidated).toBe(true)
    expect(client.getQueryState(unrelatedKey)?.isInvalidated).toBe(false)
    expect(onConfirm).not.toHaveBeenCalled()
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it('does not invalidate a replacement list Query after the original one was removed', async () => {
    const response = deferred<{ id: string; status: string }>()
    const hook = await mount()
    await prepareFile(hook)
    const client = hook.result.current.queryClient
    const key = queryKeys.documents.list({ limit: 100 })
    client.setQueryData(key, { items: [], total: 0 })
    api.documents.createFromChunks.mockReturnValue(response.promise)
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.submitChunks()
    })
    hook.unmount()
    client.removeQueries({ queryKey: key, exact: true })
    const replacement = { items: [], total: 3 }
    client.setQueryData(key, replacement)

    await act(async () => {
      response.resolve({ id: 'created-document', status: 'completed' })
      await completion
    })

    expect(client.getQueryData(key)).toBe(replacement)
    expect(client.getQueryState(key)?.isInvalidated).toBe(false)
  })

  it('does not upload an old SHA fallback after the same user establishes a new session', async () => {
    const response = deferred<ChunkPreviewResponse>()
    const hook = await mount()
    api.documents.chunkPreview.mockResolvedValueOnce({ ...preview(), file_sha256: 'original-sha' })
    await prepareFile(hook)
    api.documents.chunkPreviewBySha.mockReturnValue(response.promise)
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.runPreview({ force: true })
    })
    act(() => session('user-a'))

    await act(async () => {
      response.reject(Object.assign(new Error('parse cache missing'), { response: { status: 404 } }))
      await completion
    })

    expect(api.documents.chunkPreview).toHaveBeenCalledOnce()
    expect(hook.result.current.error).toBeNull()
  })

  it('clears private file state and ignores an old response after another login', async () => {
    const response = deferred<ChunkPreviewResponse>()
    api.documents.chunkPreview.mockReturnValue(response.promise)
    const hook = await mount()
    act(() => hook.result.current.addFiles([new File(['private text'], 'first.md')]))
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.runPreview()
    })
    act(() => session('user-b'))

    await act(async () => {
      response.resolve(preview())
      await completion
    })

    expect(hook.result.current.fileList).toEqual([])
    expect(hook.result.current.previewData).toBeNull()
    expect(hook.result.current.runHistory).toEqual([])
  })

  it('does not share scoped file content from a retired login with a later mounted login', async () => {
    const response = deferred<{ markdown_content: string }>()
    api.parsing.listDocuments
      .mockResolvedValueOnce({
        items: [{ id: 'a-private', filename: 'a-private.md', file_type: 'md', file_size: 10 }],
        total: 1,
      })
      .mockResolvedValueOnce({
        items: [{ id: 'b-document', filename: 'b-document.md', file_type: 'md', file_size: 10 }],
        total: 1,
      })
    api.parsing.getContent.mockImplementation((id: string) =>
      id === 'a-private' ? response.promise : Promise.resolve({ markdown_content: 'user-b content' }),
    )
    const old = await mount({ waitForScope: false })
    await waitForAssertion(() => expect(api.parsing.getContent).toHaveBeenCalledWith('a-private'))
    old.unmount()
    session('user-b')
    const next = await mount({ waitForScope: false })

    await act(async () => response.resolve({ markdown_content: 'private user-a content' }))
    await waitForAssertion(() => expect(next.result.current.scopeSyncLoading).toBe(false))

    expect(next.result.current.fileList.map((item) => item.id)).toEqual(['b-document'])
    expect(api.parsing.listDocuments).toHaveBeenCalledTimes(2)
  })
})
