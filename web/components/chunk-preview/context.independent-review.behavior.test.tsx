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


describe('independent review: active view and same-user session boundaries', () => {
  it('retains an automatic active preview after appending another file', async () => {
    const hook = await mount({ autoPreview: true });
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md')]));
    await waitForAssertion(() => expect(hook.result.current.previewData?.filename).toBe('first.md'));
    act(() => hook.result.current.addFiles([new File(['second'], 'second.md')]));
    expect(hook.result.current.currentFile?.name).toBe('first.md');
    expect(hook.result.current.autoPreviewEnabled).toBe(true);
    await waitForAssertion(() => expect(hook.result.current.previewData?.filename).toBe('first.md'));
  });

  it('retains an automatic preview when its current file is clicked in the actual Sidebar', async () => {
    const hook = await mount({ autoPreview: true, children: <Sidebar /> });
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md')]));
    await waitForAssertion(() => expect(hook.result.current.previewData?.filename).toBe('first.md'));
    const currentFileButton = hook.container.querySelector<HTMLButtonElement>('button[aria-label="sidebar.fileList.selectFile"]');
    expect(currentFileButton).not.toBeNull();
    act(() => currentFileButton!.click());
    await waitForAssertion(() => expect(hook.result.current.previewData?.filename).toBe('first.md'));
  });

  it('releases single ingestion busy state after an explicit same-user login retires its result', async () => {
    const hook = await mount();
    await prepareFile(hook);
    const response = deferred<{ id: string; status: string }>();
    api.documents.createFromChunks.mockReturnValue(response.promise);
    let completion!: Promise<void>;
    act(() => { completion = hook.result.current.submitChunks(); });
    expect(hook.result.current.isSubmitting).toBe(true);
    act(() => session('user-a'));
    await act(async () => { response.resolve({ id: 'retired-created-document', status: 'completed' }); await completion; });
    expect(hook.result.current.isSubmitting).toBe(false);
  });

  it('releases batch ingestion busy state after an explicit same-user login retires its preview', async () => {
    const hook = await mount();
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md')]));
    act(() => hook.result.current.toggleIngestFileSelection(hook.result.current.currentFileItem!.id));
    const response = deferred<ChunkPreviewResponse>();
    api.documents.chunkPreview.mockReturnValue(response.promise);
    let completion!: Promise<void>;
    act(() => { completion = hook.result.current.submitSelectedFiles(); });
    expect(hook.result.current.isSubmitting).toBe(true);
    act(() => session('user-a'));
    await act(async () => { response.resolve(preview()); await completion; });
    expect(hook.result.current.isSubmitting).toBe(false);
  });

  it('releases the actual Sidebar audit control after an explicit same-user login retires its result', async () => {
    const hook = await mount({ children: <Sidebar /> });
    act(() => hook.result.current.setDatasetId('dataset-a'));
    await waitForAssertion(() => expect(hook.result.current.scopeSyncLoading).toBe(false));
    await prepareFile(hook);
    const response = deferred<unknown>();
    api.pipeline.ingestionPreview.mockReturnValue(response.promise);
    click(hook, 'sidebar.ingestionPreview.trigger');
    act(() => session('user-a'));
    await act(async () => response.reject(new Error('retired audit error')));
    const control = Array.from(hook.container.querySelectorAll('button')).find(button => button.textContent?.includes('sidebar.ingestionPreview.trigger'));
    expect(control).toBeDefined();
    expect(control!.disabled).toBe(false);
  });
});
