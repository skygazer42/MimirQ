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
import type { ChunkPreviewResponse, PipelineCapabilitiesResponse } from '@/types'
import { ChunkAutoTuneDialog } from './components/chunk-auto-tune-dialog'
import { ChunkPresetPanel } from './components/chunk-preset-panel'
import { Sidebar } from './components/workbench/sidebar-client'
import { TopBar } from './components/workbench/top-bar'
import { ChunkList } from './components/workbench/preview/chunk-list'
import { CompareFooter } from './components/workbench/compare-controls'
import { getPresetSeparator } from './utils/separators'

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
  datasets: { listAll: vi.fn() },
  pipeline: {
    listPipelinePlugins: vi.fn(),
    ingestionPreview: vi.fn(),
    buildPluginChunkReport: vi.fn(),
    generateAndImportPluginGoldenDraft: vi.fn(),
  },
  evaluations: { createRegressionRun: vi.fn() },
  parsedFiles: [] as ParsedFileData[],
  capabilities: {
    capabilities: null as PipelineCapabilitiesResponse | null,
    parserBackendAvailable: vi.fn(),
    chunkStrategyAvailable: vi.fn(),
  },
  router: { replace: vi.fn() },
  search: new URLSearchParams(),
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn(), message: vi.fn() },
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
vi.mock('@/lib/api/datasets', () => ({ datasetApi: api.datasets }))
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
  function optionText(children: React.ReactNode): string {
    return React.Children.toArray(children)
      .map((child) =>
        React.isValidElement<{ children?: React.ReactNode }>(child) ? optionText(child.props.children) : String(child),
      )
      .join('')
  }
  function Item({ children, value }: { children?: React.ReactNode; value: string }) {
    return React.createElement('option', { value }, optionText(children))
  }
  function options(children: React.ReactNode): React.ReactElement[] {
    return React.Children.toArray(children).flatMap((child) => {
      if (!React.isValidElement<{ children?: React.ReactNode; value: string }>(child)) return []
      return child.type === Item
        ? [React.cloneElement(child, { key: child.props.value })]
        : options(child.props.children)
    })
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
        options(children),
      ),
    SelectContent: ({ children }: { children?: React.ReactNode }) => children,
    SelectItem: Item,
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
  useVirtualizer: ({ count, getItemKey }: { count: number; getItemKey?: (index: number) => string | number }) => ({
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        key: getItemKey === undefined ? index : getItemKey(index),
        start: index * 140,
        size: 140,
      })),
    getTotalSize: () => count * 140,
    measureElement: vi.fn(),
    scrollToIndex: vi.fn(),
  }),
}))
vi.mock('framer-motion', async (importOriginal) => {
  const actual = await importOriginal<typeof import('framer-motion')>()
  return {
    ...actual,
    AnimatePresence: ({ children }: { children: React.ReactNode }) => children,
    useReducedMotion: () => true,
  }
})
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
  await act(async () => root.render(options.strict ? <StrictMode>{content}</StrictMode> : content))
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
  return button!
}

function changeText(input: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, value)
  act(() => input.dispatchEvent(new Event('input', { bubbles: true })))
}

function chooseSelectValue(container: HTMLElement, value: string) {
  const select = Array.from(container.querySelectorAll<HTMLSelectElement>('select')).find((element) =>
    Array.from(element.options).some((option) => option.value === value),
  )
  if (select === undefined) throw new Error(`Missing select option ${value}`)
  act(() => {
    select.value = value
    select.dispatchEvent(new Event('change', { bubbles: true }))
  })
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
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  localStorage.clear()
  sessionStorage.clear()
  clearAuthSession()
  session('user-a')
  vi.clearAllMocks()
  api.search = new URLSearchParams()
  api.parsedFiles = []
  api.capabilities.capabilities = null
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
  api.datasets.listAll.mockReset().mockResolvedValue([])
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

describe('active preview and session replacement', () => {
  it.each(['agentic_chunker', 'late_chunking', 'late_chunking_jina', 'raptor'])(
    'preserves a saved removed %s selection and blocks preview requests',
    async (strategy) => {
      localStorage.setItem('mimirq_chunk_strategy', strategy)
      api.capabilities.capabilities = {
        default_parser_backend: 'auto',
        default_chunk_strategy: 'langchain_recursive',
        pdf_backends: [],
        chunk_strategies: [{ name: 'langchain_recursive', available: true }],
      }
      api.capabilities.chunkStrategyAvailable.mockImplementation((name) => (name === strategy ? false : undefined))
      const hook = await mount()
      expect(hook.result.current.chunkStrategy).toBe(strategy)
      expect(hook.result.current.error).toContain('已移除')
      act(() => hook.result.current.addFiles([new File(['first'], 'first.md')]))
      await act(async () => hook.result.current.runPreview())
      expect(hook.result.current.chunkStrategy).toBe(strategy)
      expect(localStorage.getItem('mimirq_chunk_strategy')).toBe(strategy)
      expect(api.documents.chunkPreview).not.toHaveBeenCalled()
      expect(api.documents.chunkPreviewBySha).not.toHaveBeenCalled()
      expect(hook.result.current.error).toContain('不可用')
    },
  )

  it('retains an automatic active preview after appending another file', async () => {
    const hook = await mount({ autoPreview: true })
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md')]))
    await waitForAssertion(() => expect(hook.result.current.previewData?.filename).toBe('first.md'))
    act(() => hook.result.current.addFiles([new File(['second'], 'second.md')]))
    expect(hook.result.current.currentFile?.name).toBe('first.md')
    expect(hook.result.current.autoPreviewEnabled).toBe(true)
    await waitForAssertion(() => expect(hook.result.current.previewData?.filename).toBe('first.md'))
  })

  it('retains an automatic preview when its current file is clicked in the actual Sidebar', async () => {
    const hook = await mount({ autoPreview: true, children: <Sidebar /> })
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md')]))
    await waitForAssertion(() => expect(hook.result.current.previewData?.filename).toBe('first.md'))
    const currentFileButton = hook.container.querySelector<HTMLButtonElement>(
      'button[aria-label="sidebar.fileList.selectFile"]',
    )
    expect(currentFileButton).not.toBeNull()
    act(() => currentFileButton!.click())
    await waitForAssertion(() => expect(hook.result.current.previewData?.filename).toBe('first.md'))
  })

  it('releases single ingestion busy state after an explicit same-user login retires its result', async () => {
    const hook = await mount()
    await prepareFile(hook)
    const response = deferred<{ id: string; status: string }>()
    api.documents.createFromChunks.mockReturnValue(response.promise)
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.submitChunks()
    })
    expect(hook.result.current.isSubmitting).toBe(true)
    act(() => session('user-a'))
    await act(async () => {
      response.resolve({ id: 'retired-created-document', status: 'completed' })
      await completion
    })
    expect(hook.result.current.isSubmitting).toBe(false)
  })

  it('releases batch ingestion busy state after an explicit same-user login retires its preview', async () => {
    const hook = await mount()
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md')]))
    act(() => hook.result.current.toggleIngestFileSelection(hook.result.current.currentFileItem!.id))
    const response = deferred<ChunkPreviewResponse>()
    api.documents.chunkPreview.mockReturnValue(response.promise)
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.submitSelectedFiles()
    })
    expect(hook.result.current.isSubmitting).toBe(true)
    act(() => session('user-a'))
    await act(async () => {
      response.resolve(preview())
      await completion
    })
    expect(hook.result.current.isSubmitting).toBe(false)
  })

  it('releases the actual Sidebar audit control after an explicit same-user login retires its result', async () => {
    const hook = await mount({ children: <Sidebar /> })
    act(() => hook.result.current.setDatasetId('dataset-a'))
    await waitForAssertion(() => expect(hook.result.current.scopeSyncLoading).toBe(false))
    await prepareFile(hook)
    const response = deferred<unknown>()
    api.pipeline.ingestionPreview.mockReturnValue(response.promise)
    click(hook, 'sidebar.ingestionPreview.trigger')
    act(() => session('user-a'))
    await act(async () => response.reject(new Error('retired audit error')))
    const control = Array.from(hook.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('sidebar.ingestionPreview.trigger'),
    )
    expect(control).toBeDefined()
    expect(control!.disabled).toBe(false)
  })

  it('releases the preset list control when its same-user session is replaced', async () => {
    const response = deferred<{ items: [] }>()
    api.presets.list.mockReturnValue(response.promise)
    const hook = await mount({ children: <ChunkPresetPanel /> })
    const control = hook.container.querySelector<HTMLButtonElement>('[aria-label="chunkPresetPanel.refreshAria"]')!
    expect(control.disabled).toBe(true)
    act(() => session('user-a'))

    await act(async () => response.resolve({ items: [] }))

    expect(control.disabled).toBe(false)
  })

  it('releases a preset create control without applying its retired result', async () => {
    const response = deferred<{ id: string }>()
    api.presets.create.mockReturnValue(response.promise)
    const hook = await mount({ children: <ChunkPresetPanel /> })
    click(hook, 'chunkPresetPanel.savePreset')
    const input = hook.container.querySelector<HTMLInputElement>(
      'input[placeholder="chunkPresetPanel.namePlaceholder"]',
    )!
    changeText(input, 'Preset draft')
    const control = click(hook, 'save')
    expect(control.disabled).toBe(true)
    act(() => session('user-a'))

    await act(async () => response.resolve({ id: 'retired-preset' }))

    expect(control.disabled).toBe(false)
    expect(input.value).toBe('Preset draft')
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it('releases a preset update control without publishing its retired result', async () => {
    api.presets.list.mockResolvedValue({ items: [{ id: 'preset-a', name: 'Stored preset', payload: {} }] })
    const response = deferred<{}>()
    api.presets.update.mockReturnValue(response.promise)
    const hook = await mount({ children: <ChunkPresetPanel /> })
    const select = hook.container.querySelector('select')!
    await waitForAssertion(() => expect(select.querySelector('option[value="preset-a"]')).not.toBeNull())
    act(() => {
      select.value = 'preset-a'
      select.dispatchEvent(new Event('change', { bubbles: true }))
    })
    const control = click(hook, 'chunkPresetPanel.updatePreset')
    expect(control.disabled).toBe(true)
    act(() => session('user-a'))

    await act(async () => response.resolve({}))

    expect(control.disabled).toBe(false)
    expect(api.toast.success).not.toHaveBeenCalledWith('chunkPresetPanel.updated')
  })

  it('releases a plugin report control without publishing its retired result', async () => {
    const response = deferred<{ passed: boolean; summary: {}; sections: [] }>()
    api.pipeline.buildPluginChunkReport.mockReturnValue(response.promise)
    const hook = await preparePluginSidebar()
    const control = click(hook, 'sidebar.pythonPlugins.chunkReportBuild')
    expect(control.disabled).toBe(true)
    act(() => session('user-a'))

    await act(async () => response.resolve({ passed: true, summary: {}, sections: [] }))

    expect(control.disabled).toBe(false)
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it.each(['sidebar.pythonPlugins.importGolden', 'sidebar.pythonPlugins.importAndRunGolden'])(
    'releases %s without publishing its retired result',
    async (action) => {
      const response = deferred<unknown>()
      api.pipeline.generateAndImportPluginGoldenDraft.mockReturnValue(response.promise)
      const hook = await preparePluginSidebar()
      const control = click(hook, action)
      expect(control.disabled).toBe(true)
      act(() => session('user-a'))

      await act(async () => response.reject(new Error('retired golden request')))

      expect(control.disabled).toBe(false)
      expect(api.toast.error).not.toHaveBeenCalled()
    },
  )

  it('keeps a new-session ingestion busy when the retired submission finishes first', async () => {
    const hook = await mount()
    await prepareFile(hook)
    const previous = deferred<{ id: string; status: string }>()
    const current = deferred<{ id: string; status: string }>()
    api.documents.createFromChunks.mockReturnValueOnce(previous.promise).mockReturnValueOnce(current.promise)
    let previousCompletion!: Promise<void>
    let currentCompletion!: Promise<void>
    act(() => {
      previousCompletion = hook.result.current.submitChunks()
    })
    act(() => session('user-a'))
    act(() => {
      currentCompletion = hook.result.current.submitChunks()
    })
    expect(api.documents.createFromChunks).toHaveBeenCalledTimes(2)

    await act(async () => {
      previous.resolve({ id: 'retired-document', status: 'completed' })
      await previousCompletion
    })
    expect(hook.result.current.isSubmitting).toBe(true)
    expect(hook.result.current.createdDocumentId).toBeNull()

    await act(async () => {
      current.resolve({ id: 'current-document', status: 'completed' })
      await currentCompletion
    })
    expect(hook.result.current.isSubmitting).toBe(false)
    expect(hook.result.current.createdDocumentId).toBe('current-document')
  })
})

describe('preview submission snapshot ownership', () => {
  it.each(['submitChunks', 'submitSelectedFiles'] as const)(
    'does not silently ingest a truncated active preview through %s',
    async (action) => {
      const data = preview()
      data.chunks_truncated = true
      data.total_chunks_full = 3
      api.documents.chunkPreview.mockResolvedValue(data)
      const hook = await mount()
      act(() => hook.result.current.updatePerfSettings({ maxChunks: 1 }))
      await prepareFile(hook)
      const fileId = hook.result.current.currentFileItem!.id
      act(() => {
        hook.result.current.toggleIngestFileSelection(fileId)
        hook.result.current.updateChunkOverride(0, { content: '' })
      })

      await act(async () => hook.result.current[action]())

      expect(api.documents.createFromChunks).not.toHaveBeenCalled()
      expect(hook.result.current.error).toContain('完整预览')
      expect(hook.result.current.chunkOverrides[0].content).toBe('')
      expect(hook.result.current.selectedIngestFileIds.has(fileId)).toBe(true)
      expect(api.toast.success).not.toHaveBeenCalled()
    },
  )

  it('requests all chunks for an unseen batch target regardless of the UI preview limit', async () => {
    const hook = await mount()
    act(() =>
      hook.result.current.addFiles([new File(['current'], 'current.md'), new File(['one\ntwo\nthree'], 'batch.md')]),
    )
    const target = hook.result.current.fileList[1]
    act(() => {
      hook.result.current.toggleIngestFileSelection(target.id)
      hook.result.current.updatePerfSettings({ maxChunks: 1 })
    })
    api.documents.chunkPreview.mockImplementation(async (file: File, params: { max_chunks: number }) => {
      const data = preview(file.name, 'one\ntwo\nthree')
      const chunks = [
        { index: 4, content: 'one', length: 3, start_index: 0, end_index: 3 },
        { index: 9, content: 'two', length: 3, start_index: 4, end_index: 7 },
        { index: 12, content: 'three', length: 5, start_index: 8, end_index: 13 },
      ]
      data.chunks = params.max_chunks === 0 ? chunks : chunks.slice(0, params.max_chunks)
      data.total_chunks = data.chunks.length
      data.total_chunks_full = chunks.length
      data.chunks_truncated = data.chunks.length < chunks.length
      return data
    })

    await act(async () => hook.result.current.submitSelectedFiles())

    expect(api.documents.createFromChunks).toHaveBeenCalledOnce()
    expect(
      api.documents.createFromChunks.mock.calls[0][0].chunks.map((chunk: { content: string }) => chunk.content),
    ).toEqual(['one', 'two', 'three'])
  })

  it('preserves a completed result when a forced replacement preview fails', async () => {
    const hook = await mount()
    await prepareFile(hook)
    await act(async () => hook.result.current.submitChunks())
    const previous = hook.result.current.previewData
    act(() => hook.result.current.setSelectedChunkIndex(0))
    api.documents.chunkPreview.mockRejectedValue(new Error('replacement preview refused'))

    await act(async () => hook.result.current.runPreview({ force: true }))

    expect(hook.result.current.previewData).toBe(previous)
    expect(hook.result.current.submitSuccess).toBe(true)
    expect(hook.result.current.createdDocumentId).toBe('created-document')
    expect(hook.result.current.selectedChunkIndex).toBe(0)
    expect(hook.result.current.error).toBe('replacement preview refused')
  })

  it('does not submit the same completed preview again through Ctrl+S', async () => {
    const hook = await mount()
    await prepareFile(hook)
    await act(async () => hook.result.current.submitChunks())

    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 's', ctrlKey: true })))

    expect(api.documents.createFromChunks).toHaveBeenCalledOnce()
  })

  it.each(['s', 'Enter'])('does not run workspace Ctrl+%s while typing an unsaved chunk editor draft', async (key) => {
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    click(hook, 'chunkCard.edit')
    const editor = hook.container.querySelector<HTMLTextAreaElement>(
      'textarea[aria-label="chunkInspector.contentLabel"]',
    )
    if (editor === null) throw new Error('Missing actual editor input')
    changeText(editor, 'unsaved editor body')
    const previewCalls = api.documents.chunkPreview.mock.calls.length

    const event = new KeyboardEvent('keydown', { key, ctrlKey: true, bubbles: true, cancelable: true })
    act(() => editor.dispatchEvent(event))

    expect(api.documents.createFromChunks).not.toHaveBeenCalled()
    expect(api.documents.chunkPreview).toHaveBeenCalledTimes(previewCalls)
    expect(event.defaultPrevented).toBe(true)
    expect(editor.value).toBe('unsaved editor body')
  })

  it('rejects an outdated selected preview before batch writes and keeps its edits and selection', async () => {
    const hook = await mount()
    await prepareFile(hook)
    const fileId = hook.result.current.currentFileItem!.id
    act(() => {
      hook.result.current.toggleIngestFileSelection(fileId)
      hook.result.current.updateChunkOverride(0, { content: 'saved preview edit' })
      hook.result.current.updateSettings({ chunkSize: 900 })
    })
    expect(hook.result.current.isPreviewDirty).toBe(true)

    await act(async () => hook.result.current.submitSelectedFiles())

    expect(api.documents.createFromChunks).not.toHaveBeenCalled()
    expect(hook.result.current.error).toBe('当前预览需要更新，请重新生成后再入库。')
    expect(api.toast.error).toHaveBeenCalledExactlyOnceWith('当前预览需要更新，请重新生成后再入库。')
    expect(hook.result.current.chunkOverrides[0].content).toBe('saved preview edit')
    expect(hook.result.current.selectedIngestFileIds.has(fileId)).toBe(true)
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it('rejects a selected current preview while its replacement request is pending', async () => {
    const hook = await mount()
    await prepareFile(hook)
    act(() => hook.result.current.toggleIngestFileSelection(hook.result.current.currentFileItem!.id))
    const response = deferred<ChunkPreviewResponse>()
    api.documents.chunkPreview.mockReturnValue(response.promise)
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.runPreview({ force: true })
    })
    try {
      await act(async () => hook.result.current.submitSelectedFiles())
      expect(api.documents.createFromChunks).not.toHaveBeenCalled()
      expect(hook.result.current.error).toBe('请等待预览完成后再入库。')
    } finally {
      await act(async () => {
        response.resolve(preview())
        await completion
      })
    }
  })

  it('can ingest another selected file while the unselected current preview is outdated', async () => {
    const hook = await mount()
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md'), new File(['second'], 'second.md')]))
    await act(async () => hook.result.current.runPreview())
    const target = hook.result.current.fileList[1]
    act(() => {
      hook.result.current.toggleIngestFileSelection(target.id)
      hook.result.current.updateSettings({ chunkSize: 900 })
    })

    await act(async () => hook.result.current.submitSelectedFiles())

    expect(api.documents.createFromChunks).toHaveBeenCalledOnce()
    expect(api.documents.createFromChunks.mock.calls[0][0]).toMatchObject({ filename: 'second.md' })
    expect(hook.result.current.processedStatus[target.id]).toBe('success')
  })

  it.each(['submitChunks', 'submitSelectedFiles'] as const)(
    'does not publish an old %s result into a newer preview of the same file',
    async (action) => {
      const onConfirm = vi.fn()
      const hook = await mount({ onConfirm })
      await prepareFile(hook)
      const fileId = hook.result.current.currentFileItem!.id
      act(() => hook.result.current.toggleIngestFileSelection(fileId))
      const response = deferred<{ id: string; status: string }>()
      api.documents.createFromChunks.mockReturnValue(response.promise)
      let completion!: Promise<void>
      act(() => {
        completion = hook.result.current[action]()
      })
      api.documents.chunkPreview.mockResolvedValue(preview('first.md', 'newer preview body'))
      await act(async () => hook.result.current.runPreview({ force: true }))
      await act(async () => {
        response.resolve({ id: 'created-old-preview', status: 'completed' })
        await completion
      })

      expect(hook.result.current.previewData?.chunks[0].content).toBe('newer preview body')
      expect(hook.result.current.createdDocumentId).toBeNull()
      expect(hook.result.current.submitSuccess).toBe(false)
      expect(hook.result.current.processedStatus[fileId]).toBe('success')
      expect(onConfirm).not.toHaveBeenCalled()
      expect(api.toast.success).not.toHaveBeenCalled()
    },
  )

  it('does not publish completion into edits made after a single submission started', async () => {
    const onConfirm = vi.fn()
    const hook = await mount({ onConfirm })
    await prepareFile(hook)
    const response = deferred<{ id: string; status: string }>()
    api.documents.createFromChunks.mockReturnValue(response.promise)
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.submitChunks()
    })
    act(() => hook.result.current.updateChunkOverride(0, { content: 'new unsent body' }))
    await act(async () => {
      response.resolve({ id: 'created-original-body', status: 'completed' })
      await completion
    })

    expect(hook.result.current.chunkOverrides[0].content).toBe('new unsent body')
    expect(hook.result.current.submitSuccess).toBe(false)
    expect(hook.result.current.createdDocumentId).toBeNull()
    expect(onConfirm).not.toHaveBeenCalled()
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it.each(['submitChunks', 'submitSelectedFiles'] as const)(
    'checks the original document when %s is retried after a status read failure',
    async (submit) => {
      const hook = await mount()
      await prepareFile(hook)
      if (submit === 'submitSelectedFiles') {
        const fileId = hook.result.current.fileList[0].id
        act(() => hook.result.current.toggleIngestFileSelection(fileId))
      }
      api.documents.createFromChunks.mockResolvedValue({ id: 'created-once', status: 'processing' })
      api.documents.getStatus.mockRejectedValueOnce(new Error('状态接口暂不可用'))

      vi.useFakeTimers()
      try {
        await act(async () => {
          const completion = hook.result.current[submit]()
          await vi.advanceTimersByTimeAsync(1500)
          await completion
        })
        expect(hook.result.current.error).toContain('文档已创建，入库状态未确认')
        expect(hook.result.current.createdDocumentId).toBe('created-once')

        await act(async () => {
          const completion = hook.result.current[submit]()
          await vi.advanceTimersByTimeAsync(1500)
          await completion
        })
        expect(api.documents.createFromChunks).toHaveBeenCalledOnce()
        expect(api.documents.getStatus).toHaveBeenLastCalledWith('created-once')
        expect(hook.result.current.submitSuccess).toBe(true)
      } finally {
        vi.useRealTimers()
      }
    },
  )

  it('does not keep a completed submission attached to later unsent edits', async () => {
    const hook = await mount()
    await prepareFile(hook)
    await act(async () => hook.result.current.submitChunks())
    expect(hook.result.current.submitSuccess).toBe(true)
    act(() => hook.result.current.updateChunkOverride(0, { content: '' }))

    expect(hook.result.current.submitSuccess).toBe(false)
    expect(hook.result.current.createdDocumentId).toBeNull()
    expect(hook.result.current.chunkOverrides[0].content).toBe('')
  })

  it('keeps only failed batch targets selected and exposes their actual write error', async () => {
    const hook = await mount()
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md'), new File(['second'], 'second.md')]))
    const ids = hook.result.current.fileList.map((item) => item.id)
    act(() => ids.forEach((id) => hook.result.current.toggleIngestFileSelection(id)))
    api.documents.createFromChunks
      .mockRejectedValueOnce(new Error('write refused'))
      .mockResolvedValueOnce({ id: 'created-second', status: 'completed' })

    await act(async () => hook.result.current.submitSelectedFiles())

    expect(hook.result.current.selectedIngestFileIds).toEqual(new Set([ids[0]]))
    expect(hook.result.current.processedStatus).toMatchObject({ [ids[0]]: 'error', [ids[1]]: 'success' })
    expect(hook.result.current.error).toBe('write refused')
    expect(api.toast.success).not.toHaveBeenCalled()
  })

  it('does not keep a completed submission attached to changed chunk settings', async () => {
    const hook = await mount()
    await prepareFile(hook)
    await act(async () => hook.result.current.submitChunks())
    expect(hook.result.current.submitSuccess).toBe(true)

    act(() => hook.result.current.updateSettings({ chunkSize: 900 }))

    expect(hook.result.current.isPreviewDirty).toBe(true)
    expect(hook.result.current.submitSuccess).toBe(false)
    expect(hook.result.current.createdDocumentId).toBeNull()
  })
})

describe('preview file content and source identity', () => {
  function parsedSource(): ParsedFileData {
    return {
      id: 'source-a',
      filename: 'source.md',
      fileType: 'md',
      fileSize: 4,
      markdownContent: 'aaaa',
      originalMarkdownContent: 'aaaa',
      contentLoaded: true,
      parsedAt: '1970-01-01T00:00:00Z',
      parser: 'Text',
      source: 'parsing_workspace',
    }
  }

  it('keeps an explicitly loaded empty current body and real zero metadata', async () => {
    api.parsedFiles = [{ ...parsedSource(), markdownContent: '', originalMarkdownContent: 'old body', fileSize: 0 }]
    const hook = await mount()

    expect(hook.result.current.currentFile).not.toBeNull()
    expect(await hook.result.current.currentFile!.text()).toBe('')
    expect(hook.result.current.currentFileItem?.originalFileSize).toBe(0)
    expect(hook.result.current.currentFileItem?.sourceTimeMs).toBe(0)
  })

  it('keeps one document when its cached target dataset differs from the parsing storage dataset', async () => {
    api.parsedFiles = [{ ...parsedSource(), datasetId: 'target-dataset' }]
    api.parsing.listDocuments.mockResolvedValue({
      items: [
        { id: 'source-a', filename: 'source.md', file_type: 'md', file_size: 4, dataset_id: 'workspace-dataset' },
      ],
      total: 1,
    })
    api.parsing.getContent.mockResolvedValue({ markdown_content: 'aaaa' })
    const hook = await mount()

    expect(hook.result.current.fileList.map((item) => item.id)).toEqual(['source-a'])
  })

  it('shows the real epoch time in the actual Sidebar instead of an unknown timestamp', async () => {
    api.parsedFiles = [parsedSource()]
    const hook = await mount({ children: <Sidebar /> })
    const name = hook.container.querySelector<HTMLElement>('[title="source.md"]')
    const row = name?.closest('button')
    if (row === null || row === undefined) throw new Error('Missing actual source row')
    const titles = Array.from(row.querySelectorAll('[title]'), (element) => element.getAttribute('title'))
    expect(titles.some((title) => title?.includes('sidebar.fileList.timeFallback'))).toBe(false)
  })

  it('keeps an unavailable remote timestamp unknown instead of using the current time', async () => {
    api.parsing.listDocuments.mockResolvedValue({
      items: [{ id: 'source-a', filename: 'source.md', file_type: 'md', file_size: 4 }],
      total: 1,
    })
    api.parsing.getContent.mockResolvedValue({ markdown_content: 'aaaa' })
    const hook = await mount()
    expect(hook.result.current.currentFileItem?.sourceTimeMs).toBeUndefined()
  })

  it('sorts a known zero timestamp ahead of an unknown time in the actual Sidebar', async () => {
    api.parsing.listDocuments.mockResolvedValue({
      items: [
        { id: 'unknown-time', filename: 'unknown.md', file_type: 'md', file_size: 4 },
        { id: 'epoch-time', filename: 'epoch.md', file_type: 'md', file_size: 4, updated_at: '1970-01-01T00:00:00Z' },
      ],
      total: 2,
    })
    api.parsing.getContent.mockResolvedValue({ markdown_content: 'aaaa' })
    const hook = await mount({ children: <Sidebar /> })
    const names = Array.from(hook.container.querySelectorAll('[data-chunk-file-list] [title]'), (element) =>
      element.getAttribute('title'),
    ).filter((name) => name === 'unknown.md' || name === 'epoch.md')
    expect(names).toEqual(['epoch.md', 'unknown.md'])
  })

  it('exposes content read failures and retains the known local file', async () => {
    api.parsedFiles = [parsedSource()]
    api.parsing.listDocuments.mockResolvedValue({
      items: [{ id: 'source-a', filename: 'source.md', file_type: 'md', file_size: 4 }],
      total: 1,
    })
    api.parsing.getContent.mockRejectedValue(new Error('source read refused'))
    const hook = await mount()

    expect(hook.result.current.scopeSyncError).toBe('source read refused')
    expect(await hook.result.current.currentFile!.text()).toBe('aaaa')
  })

  it('can retry a failed scope read without discarding the manually uploaded input', async () => {
    api.parsing.listDocuments.mockRejectedValueOnce(new Error('scope offline')).mockResolvedValue({
      items: [{ id: 'remote-a', filename: 'remote.md', file_type: 'md', file_size: 4 }],
      total: 1,
    })
    api.parsing.getContent.mockResolvedValue({ markdown_content: 'aaaa' })
    const hook = await mount()
    expect(hook.result.current.scopeSyncError).toBe('scope offline')
    const manual = new File(['manual body'], 'manual.md')
    act(() => hook.result.current.addFiles([manual]))

    act(() => hook.result.current.reloadScopeDocuments())
    await waitForAssertion(() => expect(hook.result.current.scopeSyncLoading).toBe(false))

    expect(hook.result.current.scopeSyncError).toBeNull()
    expect(hook.result.current.currentFile).toBe(manual)
    expect(hook.result.current.fileList.map((item) => item.displayName)).toEqual(['manual.md', 'remote.md'])
  })

  it('does not restore background source files after the workbench is explicitly cleared', async () => {
    api.parsedFiles = [parsedSource()]
    const response = deferred<{
      items: Array<{ id: string; filename: string; file_type: string; file_size: number }>
      total: number
    }>()
    api.parsing.listDocuments.mockReturnValue(response.promise)
    const hook = await mount({ waitForScope: false })
    act(() => hook.result.current.clearFiles())
    await act(async () =>
      response.resolve({ items: [{ id: 'source-a', filename: 'source.md', file_type: 'md', file_size: 4 }], total: 1 }),
    )
    await waitForAssertion(() => expect(hook.result.current.scopeSyncLoading).toBe(false))

    expect(hook.result.current.fileList).toHaveLength(0)
    act(() => {
      api.parsedFiles = [{ ...parsedSource(), parser: 'updated metadata' }]
      hook.result.current.toggleSettingsPanel()
    })
    expect(hook.result.current.fileList).toHaveLength(0)
  })

  it('does not revive a removed source after an older scope request finishes', async () => {
    api.parsedFiles = [parsedSource()]
    const response = deferred<{
      items: Array<{ id: string; filename: string; file_type: string; file_size: number }>
      total: number
    }>()
    api.parsing.listDocuments.mockReturnValue(response.promise)
    const hook = await mount({ waitForScope: false })
    act(() => hook.result.current.removeFile(0))
    await act(async () =>
      response.resolve({ items: [{ id: 'source-a', filename: 'source.md', file_type: 'md', file_size: 4 }], total: 1 }),
    )
    await waitForAssertion(() => expect(hook.result.current.scopeSyncLoading).toBe(false))

    expect(hook.result.current.fileList).toHaveLength(0)
  })

  it('keeps an explicit uploaded-file focus when a saved focus arrives from the backend later', async () => {
    localStorage.setItem('mimirq_chunk_preview_focus_file_id', 'remote-a')
    const response = deferred<{
      items: Array<{ id: string; filename: string; file_type: string; file_size: number }>
      total: number
    }>()
    api.parsing.listDocuments.mockReturnValue(response.promise)
    api.parsing.getContent.mockResolvedValue({ markdown_content: 'aaaa' })
    const hook = await mount({ waitForScope: false })
    const manual = new File(['manual body'], 'manual.md')
    act(() => hook.result.current.addFiles([manual]))
    await act(async () =>
      response.resolve({ items: [{ id: 'remote-a', filename: 'remote.md', file_type: 'md', file_size: 4 }], total: 1 }),
    )
    await waitForAssertion(() => expect(hook.result.current.scopeSyncLoading).toBe(false))

    expect(hook.result.current.currentFile).toBe(manual)
  })

  it('can automatically preview an explicit manual input while unrelated scope documents are still loading', async () => {
    localStorage.setItem('mimirq_chunk_preview_focus_file_id', 'remote-a')
    const response = deferred<{ items: never[]; total: number }>()
    api.parsing.listDocuments.mockReturnValue(response.promise)
    const hook = await mount({ waitForScope: false, autoPreview: true })
    act(() => hook.result.current.addFiles([new File(['manual'], 'manual.md')]))
    try {
      await waitForAssertion(() => expect(hook.result.current.previewData?.filename).toBe('manual.md'))
      expect(hook.result.current.scopeSyncLoading).toBe(true)
    } finally {
      await act(async () => response.resolve({ items: [], total: 0 }))
    }
  })

  it.each(['', '  body\n\n'])(
    'keeps the remote current body exactly, including a legitimate empty string: %j',
    async (body) => {
      api.parsing.listDocuments.mockResolvedValue({
        items: [
          {
            id: 'source-a',
            filename: 'source.md',
            file_type: 'md',
            file_size: 0,
            updated_at: '1970-01-01T00:00:00Z',
          },
        ],
        total: 1,
      })
      api.parsing.getContent.mockResolvedValue({ markdown_content: body, original_markdown_content: 'old body' })
      const hook = await mount()

      expect(await hook.result.current.currentFile!.text()).toBe(body)
      expect(hook.result.current.currentFileItem?.originalFileSize).toBe(0)
      expect(hook.result.current.currentFileItem?.sourceTimeMs).toBe(0)
    },
  )

  it.each([
    { available: false, markdown_truncated: false, original_markdown_truncated: false },
    { available: true, markdown_truncated: true, original_markdown_truncated: false },
    { available: true, markdown_truncated: false, original_markdown_truncated: true },
  ])('does not preview unavailable or partial knowledge content: %j', async (flags) => {
    localStorage.setItem('mimirq_chunk_preview_dataset_id', 'dataset-a')
    api.documents.list.mockResolvedValue({
      items: [{ id: 'source-a', filename: 'source.md', file_type: 'md', file_size: 4, dataset_id: 'dataset-a' }],
      total: 1,
    })
    api.documents.getParsedContent.mockResolvedValue({
      ...flags,
      document_id: 'source-a',
      markdown_content: 'incomplete prefix',
      original_markdown_content: 'incomplete prefix',
      max_chars: 2_000_000,
    })
    const hook = await mount()

    expect(hook.result.current.scopeSyncError).not.toBeNull()
    expect(hook.result.current.fileList).toHaveLength(0)
    expect(api.documents.chunkPreview).not.toHaveBeenCalled()
  })

  it('preserves the active File and unsaved editor when another cached file is appended', async () => {
    const source = parsedSource()
    api.parsedFiles = [source]
    api.parsing.listDocuments.mockResolvedValue({
      items: [{ id: 'source-a', filename: 'source.md', file_type: 'md', file_size: 4 }],
      total: 1,
    })
    api.parsing.getContent.mockResolvedValue({ markdown_content: 'old body' })
    const hook = await mount({ children: <ChunkList /> })
    await act(async () => hook.result.current.runPreview())
    const file = hook.result.current.currentFile
    click(hook, 'chunkCard.edit')
    const editor = hook.container.querySelector<HTMLTextAreaElement>(
      'textarea[aria-label="chunkInspector.contentLabel"]',
    )
    if (editor === null) throw new Error('Missing actual editor input')
    changeText(editor, 'unsaved editor draft')

    act(() => {
      api.parsedFiles = [source, { ...source, id: 'source-b', filename: 'other.md' }]
      hook.result.current.toggleSettingsPanel()
    })

    expect(hook.result.current.currentFile).toBe(file)
    expect(hook.container.contains(editor)).toBe(true)
    expect(editor.value).toBe('unsaved editor draft')
  })

  it('keeps the current remote document selected when a different cached document arrives first', async () => {
    api.parsing.listDocuments.mockResolvedValue({
      items: [{ id: 'remote-a', filename: 'remote.md', file_type: 'md', file_size: 4 }],
      total: 1,
    })
    api.parsing.getContent.mockResolvedValue({ markdown_content: 'aaaa' })
    const hook = await mount({ children: <ChunkList /> })
    await act(async () => hook.result.current.runPreview())
    click(hook, 'chunkCard.edit')
    const editor = hook.container.querySelector<HTMLTextAreaElement>(
      'textarea[aria-label="chunkInspector.contentLabel"]',
    )
    if (editor === null) throw new Error('Missing actual editor input')
    changeText(editor, 'unsaved remote draft')

    act(() => {
      api.parsedFiles = [{ ...parsedSource(), id: 'cached-b', filename: 'cached.md' }]
      hook.result.current.toggleSettingsPanel()
    })

    expect(hook.result.current.currentFileItem?.id).toBe('remote-a')
    expect(hook.result.current.fileList.map((item) => item.id)).toEqual(['remote-a', 'cached-b'])
    expect(hook.container.contains(editor)).toBe(true)
    expect(editor.value).toBe('unsaved remote draft')
  })

  it('keeps the current document identity when a refreshed scope removes an earlier noncurrent row', async () => {
    const documents = ['a', 'b', 'c'].map((id) => ({ id, filename: `${id}.md`, file_type: 'md', file_size: 1 }))
    api.parsing.listDocuments.mockResolvedValue({ items: documents, total: documents.length })
    api.parsing.getContent.mockImplementation(async (id: string) => ({ markdown_content: id }))
    const hook = await mount()
    act(() => hook.result.current.setCurrentFileIndex(1))
    await act(async () => hook.result.current.runPreview())
    const previous = hook.result.current.previewData
    api.parsing.listDocuments.mockResolvedValue({ items: documents.slice(1), total: 2 })

    act(() => hook.result.current.reloadScopeDocuments())
    await waitForAssertion(() => expect(hook.result.current.scopeSyncLoading).toBe(false))

    expect(hook.result.current.currentFileItem?.id).toBe('b')
    expect(hook.result.current.currentFileIndex).toBe(0)
    expect(hook.result.current.previewData).toBe(previous)
  })

  it('keeps an open draft when the backing source changes until a new preview is requested', async () => {
    const source = parsedSource()
    api.parsedFiles = [source]
    const hook = await mount({ children: <ChunkList /> })
    await act(async () => hook.result.current.runPreview())
    const previous = hook.result.current.previewData
    const previousFile = hook.result.current.currentFile
    click(hook, 'chunkCard.edit')
    const editor = hook.container.querySelector<HTMLTextAreaElement>(
      'textarea[aria-label="chunkInspector.contentLabel"]',
    )
    if (editor === null) throw new Error('Missing actual editor input')
    changeText(editor, 'unsaved editor draft')

    act(() => {
      api.parsedFiles = [{ ...source, markdownContent: 'bbbb', originalMarkdownContent: 'bbbb' }]
      hook.result.current.toggleSettingsPanel()
    })

    expect(hook.result.current.previewData).toBe(previous)
    expect(hook.result.current.previewSourceFile).toBe(previousFile)
    expect(hook.result.current.isPreviewDirty).toBe(true)
    expect(hook.container.contains(editor)).toBe(true)
    expect(editor.value).toBe('unsaved editor draft')

    await act(async () => hook.result.current.runPreview())
    expect(hook.result.current.previewData).not.toBe(previous)
    expect(hook.container.contains(editor)).toBe(false)
  })

  it('does not attach an accepted older write status to a newer source revision', async () => {
    const source = parsedSource()
    api.parsedFiles = [source]
    const hook = await mount()
    await act(async () => hook.result.current.runPreview())
    const key = queryKeys.documents.list({ limit: 100 })
    hook.result.current.queryClient.setQueryData(key, { items: [], total: 0 })
    const response = deferred<{ id: string; status: string }>()
    api.documents.createFromChunks.mockReturnValue(response.promise)
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.submitChunks()
    })
    act(() => {
      api.parsedFiles = [{ ...source, markdownContent: 'bbbb', originalMarkdownContent: 'bbbb' }]
      hook.result.current.toggleSettingsPanel()
    })

    expect(hook.result.current.processedStatus[source.id]).toBeUndefined()

    await act(async () => {
      response.resolve({ id: 'created-older-source', status: 'completed' })
      await completion
    })
    expect(hook.result.current.isSubmitting).toBe(false)
    expect(hook.result.current.processedStatus[source.id]).toBeUndefined()
    expect(hook.result.current.createdDocumentId).toBeNull()
    expect(hook.result.current.submitSuccess).toBe(false)
    expect(hook.result.current.queryClient.getQueryState(key)?.isInvalidated).toBe(true)
  })

  it('retains the selected new source revision after an older batch version completes', async () => {
    const source = parsedSource()
    api.parsedFiles = [source]
    const hook = await mount()
    await act(async () => hook.result.current.runPreview())
    act(() => hook.result.current.toggleIngestFileSelection(source.id))
    const response = deferred<{ id: string; status: string }>()
    api.documents.createFromChunks.mockReturnValue(response.promise)
    let completion!: Promise<void>
    act(() => {
      completion = hook.result.current.submitSelectedFiles()
    })
    act(() => {
      api.parsedFiles = [{ ...source, markdownContent: 'bbbb', originalMarkdownContent: 'bbbb' }]
      hook.result.current.toggleSettingsPanel()
    })
    await act(async () => {
      response.resolve({ id: 'created-older-batch', status: 'completed' })
      await completion
    })

    expect(hook.result.current.selectedIngestFileIds.has(source.id)).toBe(true)
    expect(hook.result.current.processedStatus[source.id]).toBeUndefined()
    expect(hook.result.current.submitSuccess).toBe(false)
  })

  it('does not reuse old content when one document gets same-size text with the same file timestamps', async () => {
    const OriginalFile = globalThis.File
    class FixedTimeFile extends OriginalFile {
      constructor(parts: BlobPart[], name: string, options?: FilePropertyBag) {
        super(parts, name, { ...options, lastModified: 1700000000000 })
      }
    }
    vi.stubGlobal('File', FixedTimeFile)
    try {
      const source = parsedSource()
      api.parsedFiles = [source]
      api.documents.chunkPreview.mockImplementation(async (file: File) => preview(file.name, await file.text()))
      const hook = await mount()
      await act(async () => hook.result.current.runPreview())
      const previousFile = hook.result.current.currentFile!
      act(() => {
        api.parsedFiles = [{ ...source, markdownContent: 'bbbb', originalMarkdownContent: 'bbbb' }]
        hook.result.current.toggleSettingsPanel()
      })
      const currentFile = hook.result.current.currentFile!
      expect([currentFile.name, currentFile.size, currentFile.lastModified]).toEqual([
        previousFile.name,
        previousFile.size,
        previousFile.lastModified,
      ])

      await act(async () => hook.result.current.runPreview())

      expect(hook.result.current.cacheHit).toBe(false)
      expect(hook.result.current.previewData?.chunks[0].content).toBe('bbbb')
    } finally {
      vi.stubGlobal('File', OriginalFile)
    }
  })
})

describe('chunk preview workspace state and request lifetime', () => {
  it.each(['toString', 'constructor', '__proto__', 'unknown'])(
    'renders the paragraph fallback for an unrecognized stored preset %s',
    async (preset) => {
      localStorage.setItem('mimirq_chunk_preview_separator_settings', JSON.stringify({ separatorPreset: preset }))
      const hook = await mount({ children: <Sidebar /> })
      act(() => hook.result.current.updateSettings({ strategy: 'separator' }))

      expect(hook.result.current.separatorPreset).toBe(preset)
      expect(hook.container.textContent).toContain('sidebar.separator.effectiveSeparator')
      expect(getPresetSeparator(preset)).toBe('\n\n')
    },
  )

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
    const response = deferred<string>()
    clipboard().readText.mockReturnValue(response.promise)
    const hook = await mount({ children: <TopBar onOpenDocuments={() => undefined} /> })
    act(() => hook.result.current.setDatasetId('dataset-a'))
    await waitForAssertion(() => expect(hook.result.current.scopeSyncLoading).toBe(false))
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md')]))

    click(hook, 'topBar.actions.importConfigFromClipboard')
    act(() => hook.result.current.pipeline.updateOption('chunk_merge_small_min_chars', 321))
    await act(async () =>
      response.resolve(
        JSON.stringify({
          parser_backend: 'marker',
          chunk_strategy: 'separator',
          chunk_size: '600',
          chunk_overlap: '90',
          separator: String.raw`\t`,
          keep_separator: false,
          pipeline: { chunk_vector_enabled: true },
        }),
      ),
    )
    await waitForAssertion(() => expect(api.toast.success).toHaveBeenCalledWith('topBar.toasts.importedFromClipboard'))

    expect(hook.result.current).toMatchObject({
      datasetId: 'dataset-a',
      parserBackend: 'marker',
      chunkStrategy: 'separator',
      chunkSize: 600,
      chunkOverlap: 0,
      separatorCustom: String.raw`\t`,
      keepSeparator: false,
    })
    expect(hook.result.current.pipeline.options.chunk_merge_small_min_chars).toBe(321)
  })

  it('keeps settings from the current workspace when a config contains an unsupported pipeline option', async () => {
    clipboard().readText.mockResolvedValue(
      JSON.stringify({ dataset_id: 'other-dataset', chunk_size: 600, pipeline: { sparse_enabled: true } }),
    )
    const hook = await mount({ children: <TopBar onOpenDocuments={() => undefined} /> })
    act(() => hook.result.current.addFiles([new File(['first'], 'first.md')]))
    const { datasetId, chunkSize } = hook.result.current

    click(hook, 'topBar.actions.importConfigFromClipboard')

    await waitForAssertion(() =>
      expect(api.toast.error).toHaveBeenCalledWith(expect.stringContaining('sparse_enabled')),
    )
    expect(hook.result.current).toMatchObject({ datasetId, chunkSize })
    expect(api.toast.success).not.toHaveBeenCalledWith('topBar.toasts.importedFromClipboard')
  })

  it('copies and restores the current parent-child draft with an older preview on screen', async () => {
    const output = clipboard()
    const hook = await mount({ children: <TopBar onOpenDocuments={() => undefined} /> })
    await prepareFile(hook)
    act(() => {
      hook.result.current.setParserBackend('marker')
      hook.result.current.updateSettings({ strategy: 'parent_child', chunkSize: 800, chunkOverlap: 120 })
      hook.result.current.updateParentChildSettings({ parentChildRatio: 0.4, parentChildMinChildSize: 160 })
    })

    click(hook, 'topBar.actions.copyConfig')
    const exportedConfig = output.writeText.mock.calls[0][0]
    expect(JSON.parse(exportedConfig)).toMatchObject({
      parser_backend: 'marker',
      chunk_strategy: 'parent_child',
      chunk_size: 800,
      chunk_overlap: 120,
      child_ratio: 0.4,
      min_child_size: 160,
      dataset_id: null,
      pipeline: null,
    })

    act(() => {
      hook.result.current.updateParentChildSettings({ parentChildRatio: 0.6, parentChildMinChildSize: 200 })
      hook.result.current.pipeline.setEnabled(true)
    })
    output.readText.mockResolvedValue(exportedConfig)
    click(hook, 'topBar.actions.importConfigFromClipboard')
    await waitForAssertion(() => expect(api.toast.success).toHaveBeenCalledWith('topBar.toasts.importedFromClipboard'))

    expect(hook.result.current).toMatchObject({ parentChildRatio: 0.4, parentChildMinChildSize: 160 })
    expect(hook.result.current.pipeline.enabled).toBe(false)
  })

  it('restores the exact separator and pipeline settings stored in an existing preset', async () => {
    const separator = ' \t"\\t"\n '
    api.presets.list.mockResolvedValue({
      items: [
        {
          id: 'custom-preset',
          name: 'Custom separator',
          payload: {
            chunk_strategy: 'separator',
            separator_preset: 'custom',
            separator,
            keep_separator: false,
            pipeline: { enabled: false, options: { chunk_size: 900 } },
          },
        },
      ],
    })
    const hook = await mount({ children: <ChunkPresetPanel /> })
    await waitForAssertion(() => expect(hook.container.querySelector('option[value="custom-preset"]')).not.toBeNull())

    chooseSelectValue(hook.container, 'custom-preset')

    expect(hook.result.current.buildChunkPreviewRequestParams()).toMatchObject({
      chunk_strategy: 'separator',
      separator,
      keep_separator: false,
    })
    expect(hook.result.current.pipeline).toMatchObject({ enabled: false, options: { chunk_size: 900 } })
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
    const hook = await mount({ children: <TopBar onOpenDocuments={() => undefined} /> })
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
    const approve = Array.from(hook.container.querySelectorAll<HTMLButtonElement>('button')).find(
      (button) => button.textContent?.trim() === '标记已复核',
    )!

    act(() => approve.click())

    expect(hook.result.current.chunkOverrides[0].metadata?.review_status).toBe('approved')
    expect(hook.container.textContent).toContain('321 token')
  })

  it('does not reuse the backend token estimate for an actual content edit', async () => {
    const data = preview()
    data.params.unit = 'tokens'
    data.chunks[0].tokens_est = 321
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    act(() => hook.result.current.updateChunkOverride(0, { content: 'new text for display' }))

    expect(hook.container.textContent).not.toContain('321 token')
    expect(hook.container.textContent).toContain('- token')
    expect(hook.container.textContent).toContain('new text for display')
  })

  it('projects real chunk-index edits into the list without adding export-only skip metadata', async () => {
    const data = preview()
    data.chunks[0].index = 4
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    act(() => hook.result.current.updateChunkOverride(4, { content: '  😀\n````\nbody  \n', disabled: true }))

    expect(hook.container.textContent).toContain('16 字')
    expect(hook.container.textContent).toContain('已跳过')
    expect(hook.result.current.chunkOverrides[4].metadata).toBeUndefined()
    expect(data.chunks[0].content).not.toContain('😀')
  })

  it('maps a list-position approval to the actual backend chunk index', async () => {
    const data = preview()
    data.chunks[0] = { ...data.chunks[0], index: 4, metadata: { needs_review: true, weight: 0 } }
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    click(hook, '标记已复核')

    expect(hook.result.current.chunkOverrides[4]?.metadata).toMatchObject({ review_status: 'approved', weight: 0 })
    expect(hook.result.current.chunkOverrides[0]).toBeUndefined()
  })

  it('counts pending, reviewed and skipped chunks independently in the status footer', async () => {
    const data = preview()
    data.chunks[0] = { ...data.chunks[0], index: 4, metadata: { needs_review: true } }
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <CompareFooter onOpenDocuments={vi.fn()} /> })
    await prepareFile(hook)
    const footer = hook.container.querySelector('footer')!
    expect(footer.textContent).toContain('1 项待复核')

    act(() => hook.result.current.updateChunkOverride(4, { metadata: { review_status: 'approved' } }))
    expect(footer.textContent).toContain('1 项已复核')
    expect(footer.textContent).not.toContain('待复核')

    act(() => hook.result.current.updateChunkOverride(4, { disabled: true }))
    expect(footer.textContent).toContain('1 项已跳过')
    expect(footer.textContent).not.toContain('已复核')
  })

  it.each(['  😀\n\n', '', 'first\r\nsecond\rthird'])(
    'copies the selected edited body verbatim: %j',
    async (content) => {
      const output = clipboard()
      const hook = await mount({ children: <ChunkList /> })
      await prepareFile(hook)
      act(() => {
        hook.result.current.updateChunkOverride(0, { content })
        hook.result.current.setSelectedChunkIndex(0)
      })
      click(hook, 'chunkList.actions.copySelected')
      await act(async () => Promise.resolve())

      expect(output.writeText).toHaveBeenCalledWith(content)
      expect(api.toast.success).toHaveBeenCalledWith('chunkList.toasts.copiedSelected')
    },
  )

  it('reports a rejected selected-copy operation instead of silently logging it', async () => {
    const output = clipboard()
    output.writeText.mockRejectedValue(new Error('Clipboard denied'))
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    act(() => hook.result.current.setSelectedChunkIndex(0))
    click(hook, 'chunkList.actions.copySelected')
    await act(async () => Promise.resolve())

    expect(api.toast.error).toHaveBeenCalledWith('chunkList.toasts.copyFailed')
    expect(api.toast.success).not.toHaveBeenCalledWith('chunkList.toasts.copiedSelected')
  })

  it('uses actual backend indices when skipping a filtered list position', async () => {
    const data = preview()
    data.chunks = [
      { ...data.chunks[0], index: 4, content: 'first body' },
      { ...data.chunks[0], index: 9, content: 'second body' },
    ]
    data.total_chunks = 2
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    const input = hook.container.querySelector<HTMLInputElement>('input[aria-label="搜索切块内容"]')
    if (input === null) throw new Error('Missing actual chunk search control')
    changeText(input, 'second')
    await waitForAssertion(() => expect(hook.container.querySelectorAll('[data-chunk-card]')).toHaveLength(1))
    click(hook, 'chunkList.toolbar.filtersWithCount')
    click(hook, 'chunkList.batch.skipFiltered')

    expect(hook.result.current.chunkOverrides[9]?.disabled).toBe(true)
    expect(hook.result.current.chunkOverrides[1]).toBeUndefined()
    expect(hook.result.current.chunkOverrides[4]).toBeUndefined()
  })

  it('shows a clipboard write failure from the actual card action', async () => {
    const output = clipboard()
    output.writeText.mockRejectedValue(new Error('Clipboard denied'))
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    click(hook, 'chunkCard.copyContent')
    await act(async () => Promise.resolve())

    expect(api.toast.error).toHaveBeenCalledWith('chunkCard.copyFailed')
    expect(api.toast.success).not.toHaveBeenCalledWith('chunkCard.copyContentSuccess')
  })

  it('copies an actual citation with a fence longer than the body backticks', async () => {
    const output = clipboard()
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    act(() => hook.result.current.updateChunkOverride(0, { content: 'before\n````\n😀after' }))
    click(hook, 'chunkCard.copyCitation')
    await act(async () => Promise.resolve())

    expect(output.writeText.mock.calls[0][0]).toContain('`````text\nbefore\n````\n😀after\n`````')
  })

  it('keeps unknown token measurements after real values in both sorts and out of bounded filters', async () => {
    const data = preview()
    data.params.unit = 'tokens'
    data.chunks = [
      { ...data.chunks[0], index: 4, tokens_est: 0 },
      { ...data.chunks[0], index: 9, tokens_est: undefined },
      { ...data.chunks[0], index: 12, tokens_est: 100 },
    ]
    data.total_chunks = 3
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    click(hook, 'chunkList.toolbar.filters')
    const sort = Array.from(hook.container.querySelectorAll<HTMLSelectElement>('select')).find((select) =>
      Array.from(select.options).some((option) => option.value === 'length_asc'),
    )
    if (sort === undefined) throw new Error('Missing actual length sort control')
    act(() => {
      sort.value = 'length_asc'
      sort.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(
      Array.from(hook.container.querySelectorAll<HTMLElement>('[data-chunk-card]'), (card) => card.dataset.chunkIndex),
    ).toEqual(['0', '2', '1'])
    act(() => {
      sort.value = 'length_desc'
      sort.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(
      Array.from(hook.container.querySelectorAll<HTMLElement>('[data-chunk-card]'), (card) => card.dataset.chunkIndex),
    ).toEqual(['2', '0', '1'])
    const maximum = hook.container.querySelector<HTMLInputElement>(
      'input[aria-label="chunkList.lengthFilter.maxAriaTokens"]',
    )
    if (maximum === null) throw new Error('Missing actual maximum token control')
    changeText(maximum, '1')
    expect(
      Array.from(hook.container.querySelectorAll<HTMLElement>('[data-chunk-card]'), (card) => card.dataset.chunkIndex),
    ).toEqual(['0'])
  })

  it('copies and submits the same payload for a chunk edited by its actual index', async () => {
    const output = clipboard()
    const data = preview()
    data.file_size = 0
    data.chunks[0] = { ...data.chunks[0], index: 4, metadata: undefined }
    api.documents.chunkPreview.mockResolvedValue(data)
    api.documents.createFromChunks.mockResolvedValue({ id: 'created-zero', status: 'completed' })
    const hook = await mount({ children: <TopBar onOpenDocuments={() => undefined} /> })
    await prepareFile(hook)
    act(() => hook.result.current.updateChunkOverride(4, { content: '' }))
    click(hook, 'topBar.actions.copyIngestPayload')
    await act(async () => hook.result.current.submitChunks())

    const payload = api.documents.createFromChunks.mock.calls[0][0]
    expect(JSON.parse(output.writeText.mock.calls[0][0])).toEqual(JSON.parse(JSON.stringify(payload)))
    expect(payload.file_size).toBe(0)
    expect(payload.chunks[0].content).toBe('')
    expect(payload.chunks[0].metadata).toBeUndefined()
    expect(data.chunks[0].content).not.toBe('')
  })

  it.each(['parent-node', 0])('groups each real child once under its actual parent identity: %j', async (parentId) => {
    const data = preview()
    data.chunk_strategy = 'parent_child'
    data.chunks = [
      {
        index: 4,
        content: 'parent',
        length: 6,
        start_index: 0,
        end_index: 30,
        metadata: { chunk_role: 'parent', node_id: parentId },
      },
      {
        index: 9,
        content: 'first child',
        length: 11,
        start_index: 0,
        end_index: 11,
        metadata: { chunk_role: 'child', parent_node_id: parentId },
      },
      {
        index: 12,
        content: 'second child',
        length: 12,
        start_index: 12,
        end_index: 24,
        metadata: { chunk_role: 'child', parent_node_id: parentId },
      },
    ]
    data.total_chunks = 3
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    click(hook, 'chunkList.toolbar.filters')
    chooseSelectValue(hook.container, 'hierarchy')

    expect(
      Array.from(hook.container.querySelectorAll<HTMLElement>('[data-chunk-card]'), (card) => card.dataset.chunkIndex),
    ).toEqual(['0', '1', '2'])
    expect(hook.container.querySelectorAll('button[aria-label="chunkList.groupToggle.collapseGroup"]')).toHaveLength(1)
  })

  it('keeps parentless children as real rows instead of promoting and duplicating the first child', async () => {
    const data = preview()
    data.chunk_strategy = 'parent_child'
    data.chunks = [
      {
        index: 9,
        content: 'first child',
        length: 11,
        start_index: 0,
        end_index: 11,
        metadata: { chunk_role: 'child', parent_id: 'omitted-parent' },
      },
      {
        index: 12,
        content: 'second child',
        length: 12,
        start_index: 12,
        end_index: 24,
        metadata: { chunk_role: 'child', parent_id: 'omitted-parent' },
      },
    ]
    data.total_chunks = 2
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    click(hook, 'chunkList.toolbar.filters')
    chooseSelectValue(hook.container, 'hierarchy')

    expect(
      Array.from(hook.container.querySelectorAll<HTMLElement>('[data-chunk-card]'), (card) => card.dataset.chunkIndex),
    ).toEqual(['0', '1'])
    expect(hook.container.querySelectorAll('button[aria-label="chunkList.groupToggle.collapseGroup"]')).toHaveLength(0)
  })

  it.each(['__mimirq_section_all__', '__mimirq_section_none__'])(
    'keeps the actual section name separate from control values: %s',
    async (sectionName) => {
      const data = preview()
      data.chunks = [
        { ...data.chunks[0], index: 4, content: 'named section', metadata: { header_path: sectionName } },
        { ...data.chunks[0], index: 9, content: 'without section', metadata: undefined },
      ]
      data.total_chunks = 2
      api.documents.chunkPreview.mockResolvedValue(data)
      const hook = await mount({ children: <ChunkList /> })
      await prepareFile(hook)
      click(hook, 'chunkList.toolbar.filters')
      const section = Array.from(hook.container.querySelectorAll<HTMLSelectElement>('select')).find((select) =>
        Array.from(select.options).some((option) => option.textContent === sectionName),
      )
      if (section === undefined) throw new Error('Missing actual section filter')
      const option = Array.from(section.options).find((candidate) => candidate.textContent === sectionName)
      if (option === undefined) throw new Error('Missing actual named section option')
      act(() => {
        section.value = option.value
        section.dispatchEvent(new Event('change', { bubbles: true }))
      })
      expect(
        Array.from(
          hook.container.querySelectorAll<HTMLElement>('[data-chunk-card]'),
          (card) => card.dataset.chunkIndex,
        ),
      ).toEqual(['0'])
      chooseSelectValue(hook.container, '__mimirq_section_all__')
      chooseSelectValue(hook.container, 'section')
      expect(
        hook.container.querySelectorAll('button[aria-label="chunkList.groupToggle.collapseSection"]'),
      ).toHaveLength(2)
    },
  )

  it('does not label absent server measurements as healthy or zero', async () => {
    const data = preview()
    data.review_signals = null
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    click(hook, 'chunkList.toolbar.filters')

    expect(hook.container.textContent).not.toContain('chunkList.filters.healthySummary')
    expect(hook.container.textContent).toContain('chunkList.toolbar.noQualitySignals')
    const short = Array.from(hook.container.querySelectorAll<HTMLButtonElement>('button')).filter(
      (button) => button.textContent?.trim() === 'chunkList.filters.shortLabel',
    )
    expect(short).toHaveLength(1)
    expect(short[0].disabled).toBe(true)
  })

  it('invalidates body-dependent markers without silently clearing an active filter or the edit', async () => {
    const data = preview()
    data.review_signals = { short_indices: [0], duplicate_indices: [], gap_indices: [], overlap_indices: [] }
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    click(hook, 'chunkList.toolbar.filters')
    click(hook, 'chunkList.filters.shortLabel')
    act(() => hook.result.current.updateChunkOverride(0, { content: 'long body '.repeat(100) }))

    expect(hook.container.textContent).toContain('chunkList.states.unavailableSignals')
    expect(hook.container.textContent).not.toContain('chunkList.states.noMatches')
    expect(hook.result.current.chunkOverrides[0].content).toBe('long body '.repeat(100))
  })

  it('keeps valid server short markers after a manual approval', async () => {
    const data = preview()
    data.chunks[0].metadata = { needs_review: true }
    data.review_signals = { short_indices: [0] }
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    click(hook, '标记已复核')

    expect(hook.container.textContent).toContain('内容偏短')
    expect(hook.result.current.chunkOverrides[0].metadata?.reviewed).toBe(true)
  })

  it('keeps zero as an actual maximum-length bound', async () => {
    const data = preview()
    data.chunks.push({ ...data.chunks[0], index: 9, content: 'nonempty', length: 8 })
    data.total_chunks = 2
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    act(() => hook.result.current.updateChunkOverride(0, { content: '' }))
    click(hook, 'chunkList.toolbar.filters')
    const maximum = hook.container.querySelector<HTMLInputElement>(
      'input[aria-label="chunkList.lengthFilter.maxAriaChars"]',
    )
    if (maximum === null) throw new Error('Missing maximum length input')
    changeText(maximum, '0')

    expect(maximum.value).toBe('0')
    expect(
      Array.from(hook.container.querySelectorAll<HTMLElement>('[data-chunk-card]'), (card) => card.dataset.chunkIndex),
    ).toEqual(['0'])
  })

  it('keeps an invalid length draft visible instead of truncating it into an applied bound', async () => {
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    click(hook, 'chunkList.toolbar.filters')
    const minimum = hook.container.querySelector<HTMLInputElement>(
      'input[aria-label="chunkList.lengthFilter.minAriaChars"]',
    )
    if (minimum === null) throw new Error('Missing minimum length input')
    changeText(minimum, '1.5')

    expect(minimum.value).toBe('1.5')
    expect(hook.container.textContent).toContain('chunkList.lengthFilter.invalid')
    expect(hook.container.textContent).not.toContain('chunkList.states.noMatches')
  })

  it('resets list drafts when another cached preview of the same filename becomes current', async () => {
    const first = preview('first.md', 'first version')
    const second = preview('first.md', 'second version')
    second.params.chunk_size = 900
    api.documents.chunkPreview.mockResolvedValueOnce(first).mockResolvedValueOnce(second)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    act(() => hook.result.current.updateSettings({ chunkSize: 900 }))
    await act(async () => hook.result.current.runPreview())
    const input = hook.container.querySelector<HTMLInputElement>('input[aria-label="搜索切块内容"]')
    if (input === null) throw new Error('Missing actual list search input')
    changeText(input, 'second')
    act(() => hook.result.current.updateSettings({ chunkSize: 1000 }))
    await act(async () => hook.result.current.runPreview())

    expect(hook.result.current.cacheHit).toBe(true)
    expect(api.documents.chunkPreview).toHaveBeenCalledTimes(2)
    expect(input.value).toBe('')
    expect(hook.container.textContent).toContain('first version')
  })

  it('highlights the actual original substring after lowercase expansion', async () => {
    const data = preview('first.md', 'İ😀hit')
    data.total_characters = 5
    data.file_size = 9
    data.chunks[0].length = 5
    data.chunks[0].end_index = 5
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    const input = hook.container.querySelector<HTMLInputElement>('input[aria-label="搜索切块内容"]')
    if (input === null) throw new Error('Missing actual list search input')
    changeText(input, 'hit')
    await waitForAssertion(() => expect(hook.container.querySelector('mark')?.textContent).toBe('hit'))
  })

  it('retains computed local search results when the panel is collapsed', async () => {
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    click(hook, 'chunkList.retrieve.trigger')
    const input = hook.container.querySelector<HTMLInputElement>(
      'input[placeholder="chunkList.retrieve.queryPlaceholder"]',
    )
    if (input === null) throw new Error('Missing actual ranked query input')
    changeText(input, 'first')
    expect(hook.container.textContent).toContain('chunkList.retrieve.trigger 1')
    click(hook, 'chunkList.retrieve.trigger 1')
    expect(hook.container.textContent).toContain('chunkList.retrieve.trigger 1')
  })

  it('reveals a full-preview search hit hidden by the current list filter', async () => {
    const data = preview()
    data.chunks = [
      { ...data.chunks[0], index: 4, content: 'visible paragraph' },
      { ...data.chunks[0], index: 9, content: 'hidden target' },
    ]
    data.total_chunks = 2
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    const listQuery = hook.container.querySelector<HTMLInputElement>('input[aria-label="搜索切块内容"]')
    if (listQuery === null) throw new Error('Missing list query')
    changeText(listQuery, 'visible')
    await waitForAssertion(() => expect(hook.container.querySelectorAll('[data-chunk-card]')).toHaveLength(1))
    click(hook, 'chunkList.retrieve.trigger')
    const query = hook.container.querySelector<HTMLInputElement>(
      'input[aria-label="chunkList.retrieve.queryPlaceholder"]',
    )
    if (query === null) throw new Error('Missing ranked query')
    changeText(query, 'hidden')
    const hit = Array.from(hook.container.querySelectorAll<HTMLButtonElement>('button')).find((button) =>
      button.textContent?.includes('hidden target'),
    )
    if (hit === undefined) throw new Error('Missing actual ranked target')
    act(() => hit.click())

    expect(listQuery.value).toBe('')
    expect(hook.result.current.selectedChunkIndex).toBe(1)
    expect(hook.container.querySelector('[data-chunk-index="1"][data-selected="true"]')).not.toBeNull()
  })

  it('opens only the search target section and retains other collapse preferences', async () => {
    const data = preview()
    data.chunks = [
      { ...data.chunks[0], index: 4, content: 'hidden target', metadata: { header_path: 'A' } },
      { ...data.chunks[0], index: 9, content: 'other paragraph', metadata: { header_path: 'B' } },
    ]
    data.total_chunks = 2
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    click(hook, 'chunkList.toolbar.filters')
    chooseSelectValue(hook.container, 'section')
    for (let count = 0; count < 2; count += 1) {
      const button = hook.container.querySelector<HTMLButtonElement>(
        'button[aria-label="chunkList.groupToggle.collapseSection"]',
      )
      if (button === null) throw new Error('Missing actual section collapse control')
      act(() => button.click())
    }
    expect(hook.container.querySelectorAll('[data-chunk-card]')).toHaveLength(0)
    click(hook, 'chunkList.retrieve.trigger')
    const query = hook.container.querySelector<HTMLInputElement>(
      'input[aria-label="chunkList.retrieve.queryPlaceholder"]',
    )
    if (query === null) throw new Error('Missing ranked query')
    changeText(query, 'hidden')
    const hit = Array.from(hook.container.querySelectorAll<HTMLButtonElement>('button')).find((button) =>
      button.textContent?.includes('hidden target'),
    )
    if (hit === undefined) throw new Error('Missing actual ranked target')
    act(() => hit.click())

    expect(hook.container.querySelector('[data-chunk-index="0"][data-selected="true"]')).not.toBeNull()
    expect(hook.container.querySelector('[data-chunk-index="1"]')).toBeNull()
    expect(api.toast.info).not.toHaveBeenCalledWith('chunkList.toasts.filtersClearedForResult')
  })

  it.each([
    { draft: 'visible', expected: '' },
    { draft: 'hid', expected: 'hid' },
  ])('keeps a retrieved target visible after the pending query deadline: $draft', async ({ draft, expected }) => {
    const data = preview()
    data.chunks = [
      { ...data.chunks[0], index: 4, content: 'visible paragraph' },
      { ...data.chunks[0], index: 9, content: 'hidden target' },
    ]
    data.total_chunks = 2
    api.documents.chunkPreview.mockResolvedValue(data)
    const hook = await mount({ children: <ChunkList /> })
    await prepareFile(hook)
    click(hook, 'chunkList.retrieve.trigger')
    const rankedQuery = hook.container.querySelector<HTMLInputElement>(
      'input[aria-label="chunkList.retrieve.queryPlaceholder"]',
    )
    const listQuery = hook.container.querySelector<HTMLInputElement>('input[aria-label="搜索切块内容"]')
    if (rankedQuery === null || listQuery === null) throw new Error('Missing actual query controls')
    changeText(rankedQuery, 'hidden')
    const hit = Array.from(hook.container.querySelectorAll<HTMLButtonElement>('button')).find((button) =>
      button.textContent?.includes('hidden target'),
    )
    if (hit === undefined) throw new Error('Missing actual ranked target')
    changeText(listQuery, draft)
    act(() => hit.click())
    await act(async () => new Promise((resolve) => setTimeout(resolve, 180)))

    expect(listQuery.value).toBe(expected)
    expect(hook.container.querySelector('[data-chunk-index="1"][data-selected="true"]')).not.toBeNull()
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
    const hook = await mount({ children: <TopBar onOpenDocuments={() => undefined} /> })
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
    const hook = await mount({ children: <TopBar onOpenDocuments={() => undefined} /> })
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
    const hook = await mount({ children: <TopBar onOpenDocuments={() => undefined} /> })
    act(() => hook.result.current.setDatasetId('dataset-a'))
    await waitForAssertion(() => expect(hook.result.current.scopeSyncLoading).toBe(false))
    act(() => {
      hook.result.current.addFiles([new File(['first'], 'first.md')])
      hook.result.current.updateSettings({ strategy: 'separator' })
      hook.result.current.updateSeparatorSettings({
        separatorPreset: 'custom',
        separatorCustom: String.raw`a'b\nc`,
      })
    })

    click(hook, 'topBar.actions.copyCurl')

    const text = output.writeText.mock.calls[0][0] as string
    const lines = text.split('\n')
    expect(lines.slice(0, -1).every((line) => line.endsWith(' \\') && !line.endsWith(' \\\\'))).toBe(true)
    expect(lines[0]).toContain('chunk_overlap=0')
    expect(lines[0]).toContain('include_review_signals=true')
    expect(text).toContain("--form-string $'dataset_id=dataset-a'")
    expect(text).toContain(String.raw`--form-string $'separator=a\'b\nc'`)
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

  it('applies a measured auto-tune result and previews its settings', async () => {
    const withSha = { ...preview(), file_sha256: 'first-sha' }
    api.documents.chunkPreview.mockResolvedValue(withSha)
    api.documents.chunkPreviewBySha.mockImplementation(
      async (params: { chunk_size: number; chunk_overlap: number }) => ({
        ...withSha,
        stats: {
          count: 1,
          avg: 10,
          p90: 10,
          short_count: 0,
          coverage_ratio: 1,
          overlap_waste_ratio: params.chunk_size === 600 && params.chunk_overlap === 60 ? undefined : 0,
        },
      }),
    )
    const hook = await mount({ children: <ChunkAutoTuneDialog /> })
    await prepareFile(hook)
    click(hook, 'autoTune.trigger.label')
    click(hook, 'autoTune.actions.start')
    await waitForAssertion(() => expect(hook.container.textContent).toContain('autoTune.actions.applyAndPreview'))
    expect(api.documents.chunkPreviewBySha.mock.calls[0][0]).toMatchObject({
      include_chunks: false,
      include_original_text: false,
      include_review_signals: false,
    })
    const apply = Array.from(hook.container.querySelectorAll('button')).find(
      (button) => button.textContent?.trim() === 'autoTune.actions.applyAndPreview',
    )!

    await act(async () => apply.click())

    expect(hook.result.current.chunkSize).toBe(600)
    expect(api.documents.chunkPreviewBySha.mock.lastCall?.[0]).toMatchObject({ chunk_size: 600, chunk_overlap: 90 })
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

    await act(async () => {
      await expect(
        hook.result.current.handleDrop(drop([fileEntry(new File(['first'], 'first.md')), failed])),
      ).rejects.toBe(error)
    })

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

  it('does not restore a locally selected chunk while clearing its URL', async () => {
    const hook = await mount()
    await prepareFile(hook)
    act(() => hook.result.current.setSelectedChunkIndex(0))
    expect(api.router.replace).toHaveBeenCalledWith('/chunk-preview?chunk=1')

    act(() => {
      api.search = new URLSearchParams('chunk=1')
      hook.result.current.setSelectedChunkIndex(null)
    })
    expect(api.router.replace).toHaveBeenCalledWith('/chunk-preview')

    api.documents.chunkPreview.mockResolvedValueOnce(preview('first.md', 'replacement preview'))
    await act(async () => hook.result.current.runPreview({ force: true }))
    expect(hook.result.current.selectedChunkIndex).toBeNull()
  })

  it('replaces a queued chunk URL update when the selection is cleared first', async () => {
    const hook = await mount()
    await prepareFile(hook)
    const previousCalls = api.router.replace.mock.calls.length

    act(() => hook.result.current.setSelectedChunkIndex(0))
    act(() => hook.result.current.setSelectedChunkIndex(null))

    expect(api.router.replace.mock.calls.slice(previousCalls)).toEqual([['/chunk-preview?chunk=1'], ['/chunk-preview']])

    act(() => {
      api.search = new URLSearchParams('chunk=1')
      hook.result.current.setHoveredChunkIndex(0)
    })
    expect(hook.result.current.selectedChunkIndex).toBeNull()
  })

  it('removes the previous chunk number in the dataset navigation itself', async () => {
    api.search = new URLSearchParams('dataset_id=dataset-a')
    const hook = await mount()
    await prepareFile(hook)
    act(() => hook.result.current.setSelectedChunkIndex(0))
    act(() => {
      api.search = new URLSearchParams('dataset_id=dataset-a&chunk=1')
      hook.result.current.setHoveredChunkIndex(0)
    })
    const previousCalls = api.router.replace.mock.calls.length

    await act(async () => hook.result.current.setDatasetId('dataset-b'))

    expect(hook.result.current.selectedChunkIndex).toBeNull()
    expect(api.router.replace.mock.calls.slice(previousCalls)).toEqual([['/chunk-preview?dataset_id=dataset-b']])
  })

  it('ignores an incoming chunk position containing nonnumeric characters', async () => {
    api.search = new URLSearchParams('chunk=1extra')
    const hook = await mount()
    await prepareFile(hook)

    expect(hook.result.current.selectedChunkIndex).toBeNull()
  })

  it('reuses a valid preview for the same file and settings', async () => {
    const hook = await mount()
    await prepareFile(hook)

    await act(async () => hook.result.current.runPreview())

    expect(api.documents.chunkPreview).toHaveBeenCalledOnce()
    expect(hook.result.current.cacheHit).toBe(true)
  })

  it('reuses a preview when two inputs decode to the same custom separator', async () => {
    const hook = await mount()
    act(() => {
      hook.result.current.updateSettings({ strategy: 'separator' })
      hook.result.current.updateSeparatorSettings({
        separatorPreset: 'custom',
        separatorCustom: String.raw`\u002e`,
      })
    })
    await prepareFile(hook)
    expect(api.documents.chunkPreview.mock.calls[0][1]).toMatchObject({ separator: '.', chunk_overlap: 0 })

    act(() => hook.result.current.updateSeparatorSettings({ separatorCustom: '.' }))
    expect(hook.result.current.isPreviewDirty).toBe(false)
    await act(async () => hook.result.current.runPreview())

    expect(api.documents.chunkPreview).toHaveBeenCalledOnce()
    expect(api.documents.chunkPreviewBySha).not.toHaveBeenCalled()
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
