// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  documents: { preview: vi.fn(), createFromChunks: vi.fn() },
  parsing: { extract: vi.fn() },
  uploaded: vi.fn(),
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('@/lib/api', () => ({ documentApi: api.documents, parsingApi: api.parsing }))
vi.mock('@/lib/api/documents', () => ({ documentApi: api.documents }))
vi.mock('@/lib/api/parsing', () => ({ parsingApi: api.parsing }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn() }))
vi.mock('@/contexts/pipeline-capabilities-context', () => ({
  usePipelineCapabilities: () => ({ capabilities: null, parserBackendAvailable: () => undefined }),
}))
vi.mock('@/components/pipeline-options-panel', () => ({ PipelineOptionsPanel: () => null }))
vi.mock('@/components/business/parser-dropdown', () => ({ ParserDropdown: () => null }))
vi.mock('@/components/ui/dialog', async () => {
  const React = await import('react')
  const Context = React.createContext({ open: false, onOpenChange: (_open: boolean) => {} })
  function Container({ children }: { children?: React.ReactNode }) {
    return <div>{children}</div>
  }
  return {
    Dialog: ({
      open,
      onOpenChange,
      children,
    }: {
      open: boolean
      onOpenChange: (open: boolean) => void
      children?: React.ReactNode
    }) => <Context.Provider value={{ open, onOpenChange }}>{children}</Context.Provider>,
    DialogTrigger: ({ children }: { children: React.ReactElement<{ onClick?: () => void }> }) => {
      const context = React.useContext(Context)
      return React.cloneElement(children, { onClick: () => context.onOpenChange(true) })
    },
    DialogContent: ({ children }: { children?: React.ReactNode }) => {
      const context = React.useContext(Context)
      return context.open ? (
        <div role="dialog">
          <button data-testid="adapter-close" onClick={() => context.onOpenChange(false)}>
            close adapter
          </button>
          {children}
        </div>
      ) : null
    },
    DialogTitle: Container,
    DialogDescription: Container,
  }
})

import { ManualUploadDialog } from '../manual-upload-dialog'
import { ParsingExtractPanel } from './parsing-extract-panel'
import { ParserBackendProvider } from '@/contexts/parser-backend-context'
import { PipelineOptionsProvider } from '@/contexts/pipeline-options-context'
import type { DocumentPreview } from '@/types'
import type { ParsingElement, ParsingExtractResponse } from '@/lib/api/parsing'
import { clearAuthSession, setAuthSession } from '@/lib/auth-storage'

const cleanups: Array<() => void> = []
const elements: ParsingElement[] = []

function session() {
  setAuthSession({
    user: {
      id: 'review-user',
      username: 'review-user',
      email: 'review@example.test',
      is_active: true,
      created_at: '2026-11-05T00:00:00Z',
      last_login_at: null,
    },
    token: { access_token: 'review-token', token_type: 'bearer', expires_in: 3600 },
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

function preview(filename: string, content: string): DocumentPreview {
  return {
    filename,
    file_type: 'txt',
    file_size: content.length,
    parser_backend: 'auto',
    segments: [{ index: 0, content }],
  }
}

function extraction(documentId: string, value: string): ParsingExtractResponse {
  return {
    document_id: documentId,
    mode: 'schema',
    result: { field: { value, strategy: 'schema', evidence: [{ element_id: 'element-a', kind: 'seal', page: 1 }] } },
  }
}

function mount(initial: React.ReactElement) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const render = (element: React.ReactElement) => act(() => root.render(element))
  cleanups.push(() => {
    act(() => root.unmount())
    container.remove()
  })
  render(initial)
  return { container, render }
}

function click(view: ReturnType<typeof mount>, text: string) {
  const button = Array.from(view.container.querySelectorAll('button')).find((button) =>
    button.textContent?.trim().startsWith(text),
  )
  expect(button, text).toBeDefined()
  act(() => button!.click())
  return button!
}

function uploadView() {
  const view = mount(
    <ParserBackendProvider>
      <PipelineOptionsProvider>
        <ManualUploadDialog onUploaded={api.uploaded} />
      </PipelineOptionsProvider>
    </ParserBackendProvider>,
  )
  click(view, '高级切片上传')
  return view
}

function selectFile(view: ReturnType<typeof mount>, filename: string) {
  const input = view.container.querySelector<HTMLInputElement>('input[type="file"]')!
  const file = new File([filename], filename, { type: 'text/plain' })
  Object.defineProperty(input, 'files', { configurable: true, value: [file] })
  act(() => input.dispatchEvent(new Event('change', { bubbles: true })))
  return file
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  localStorage.clear()
  sessionStorage.clear()
  clearAuthSession()
  session()
  vi.clearAllMocks()
  api.documents.preview.mockReset().mockImplementation(async (file: File) => preview(file.name, `${file.name} content`))
  api.documents.createFromChunks.mockReset().mockResolvedValue({ id: 'created-document' })
  api.parsing.extract.mockReset()
})

afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
})

describe('manual upload request lifetime', () => {
  it('retires an old-session preview and releases its own busy state after the same user logs in again', async () => {
    const response = deferred<DocumentPreview>()
    api.documents.preview.mockReturnValueOnce(response.promise)
    const view = uploadView()
    selectFile(view, 'first.txt')
    act(() => session())

    await act(async () => response.resolve(preview('first.txt', 'retired session preview')))

    expect(view.container.textContent).not.toContain('retired session preview')
    expect(view.container.textContent).not.toContain('正在解析结构...')
    selectFile(view, 'second.txt')
    await act(async () => {})
    expect(view.container.textContent).toContain('second.txt content')
  })

  it('does not notify a replacement session when an older write completes and keeps the controls available', async () => {
    const response = deferred<{ id: string }>()
    api.documents.createFromChunks.mockReturnValueOnce(response.promise)
    const view = uploadView()
    selectFile(view, 'first.txt')
    await act(async () => {})
    click(view, '开始处理')
    act(() => session())

    await act(async () => response.resolve({ id: 'created-first' }))

    expect(api.uploaded).not.toHaveBeenCalled()
    expect(view.container.textContent).toContain('first.txt content')
    const button = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.startsWith('开始处理'),
    )!
    expect(button.disabled).toBe(false)
    click(view, '开始处理')
    await act(async () => {})
    expect(api.uploaded).toHaveBeenCalledOnce()
  })

  it('does not replace the selected file chunks with an older preview response', async () => {
    const previous = deferred<DocumentPreview>()
    api.documents.preview.mockReturnValueOnce(previous.promise)
    const view = uploadView()
    selectFile(view, 'first.txt')
    selectFile(view, 'second.txt')
    await act(async () => {})
    expect(view.container.textContent).toContain('second.txt content')

    await act(async () => previous.resolve(preview('first.txt', 'retired first content')))

    expect(view.container.textContent).toContain('second.txt content')
    expect(view.container.textContent).not.toContain('retired first content')
  })

  it('keeps a newer preview loading when the aborted preview settles', async () => {
    const previous = deferred<DocumentPreview>()
    const current = deferred<DocumentPreview>()
    api.documents.preview.mockReturnValueOnce(previous.promise).mockReturnValueOnce(current.promise)
    const view = uploadView()
    selectFile(view, 'first.txt')
    selectFile(view, 'second.txt')

    await act(async () => previous.reject(new Error('aborted first request')))

    expect(view.container.textContent).toContain('正在解析结构...')
    await act(async () => current.resolve(preview('second.txt', 'current content')))
  })

  it('does not revive a preview after the dialog was closed and reopened', async () => {
    const response = deferred<DocumentPreview>()
    api.documents.preview.mockReturnValue(response.promise)
    const view = uploadView()
    selectFile(view, 'first.txt')
    act(() => view.container.querySelector<HTMLButtonElement>('[data-testid="adapter-close"]')!.click())
    click(view, '高级切片上传')

    await act(async () => response.resolve(preview('first.txt', 'closed dialog content')))

    expect(view.container.textContent).not.toContain('closed dialog content')
  })

  it('preserves a newer selected file when an accepted older write completes', async () => {
    const response = deferred<{ id: string }>()
    api.documents.createFromChunks.mockReturnValue(response.promise)
    const view = uploadView()
    selectFile(view, 'first.txt')
    await act(async () => {})
    click(view, '开始处理')
    selectFile(view, 'second.txt')
    await act(async () => {})

    await act(async () => response.resolve({ id: 'created-first' }))

    expect(view.container.textContent).toContain('second.txt content')
    expect(api.uploaded).toHaveBeenCalledOnce()
  })

  it('accepts a single write from two synchronous clicks', async () => {
    const response = deferred<{ id: string }>()
    api.documents.createFromChunks.mockReturnValue(response.promise)
    const view = uploadView()
    selectFile(view, 'first.txt')
    await act(async () => {})
    const button = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.startsWith('开始处理'),
    )!
    act(() => {
      button.click()
      button.click()
    })

    expect(api.documents.createFromChunks).toHaveBeenCalledOnce()
    await act(async () => response.resolve({ id: 'created-first' }))
  })

  it('keeps the current preview and manual request snapshot intact', async () => {
    const view = uploadView()
    const file = selectFile(view, 'current.txt')
    await act(async () => {})
    expect(api.documents.preview.mock.calls[0][0]).toBe(file)
    expect(api.documents.preview.mock.calls[0][3].signal).toBeInstanceOf(AbortSignal)
    click(view, '开始处理')
    await act(async () => {})

    expect(api.documents.createFromChunks).toHaveBeenCalledWith(
      expect.objectContaining({
        filename: 'current.txt',
        chunks: [expect.objectContaining({ content: 'current.txt content' })],
        metadata: { parser_backend: 'auto' },
      }),
    )
    expect(api.uploaded).toHaveBeenCalledOnce()
  })
})

describe('extraction document ownership', () => {
  it('does not publish an older document result under the replacement document', async () => {
    const response = deferred<ParsingExtractResponse>()
    api.parsing.extract.mockReturnValue(response.promise)
    const view = mount(<ParsingExtractPanel documentId="first" activeElements={elements} />)
    click(view, '展开')
    click(view, '运行抽取')
    view.render(<ParsingExtractPanel documentId="second" activeElements={elements} />)
    click(view, '展开')

    await act(async () => response.resolve(extraction('first', 'retired extraction value')))

    expect(view.container.textContent).not.toContain('retired extraction value')
  })

  it('does not publish an older extraction failure under the replacement document', async () => {
    const response = deferred<ParsingExtractResponse>()
    api.parsing.extract.mockReturnValue(response.promise)
    const view = mount(<ParsingExtractPanel documentId="first" activeElements={elements} />)
    click(view, '展开')
    click(view, '运行抽取')
    view.render(<ParsingExtractPanel documentId="second" activeElements={elements} />)
    click(view, '展开')

    await act(async () => response.reject(new Error('retired extraction failure')))

    expect(view.container.textContent).not.toContain('retired extraction failure')
  })

  it('lets the replacement document run while an older request remains pending', async () => {
    const previous = deferred<ParsingExtractResponse>()
    const current = deferred<ParsingExtractResponse>()
    api.parsing.extract.mockReturnValueOnce(previous.promise).mockReturnValueOnce(current.promise)
    const view = mount(<ParsingExtractPanel documentId="first" activeElements={elements} />)
    click(view, '展开')
    click(view, '运行抽取')
    view.render(<ParsingExtractPanel documentId="second" activeElements={elements} />)
    click(view, '展开')
    const button = click(view, '运行抽取')

    expect(api.parsing.extract).toHaveBeenCalledTimes(2)
    await act(async () => previous.resolve(extraction('first', 'retired extraction')))
    expect(button.disabled).toBe(true)
    await act(async () => current.resolve(extraction('second', 'current extraction')))
    expect(button.disabled).toBe(false)
    expect(view.container.textContent).toContain('current extraction')
  })

  it('preserves the current payload and selectable evidence', async () => {
    const response = extraction('current', 'current value')
    api.parsing.extract.mockResolvedValue(response)
    const onSelectEvidence = vi.fn()
    const view = mount(
      <ParsingExtractPanel documentId="current" activeElements={elements} onSelectEvidence={onSelectEvidence} />,
    )
    click(view, '展开')
    click(view, '运行抽取')
    await act(async () => {})

    expect(api.parsing.extract).toHaveBeenCalledWith(
      'current',
      expect.objectContaining({ mode: 'schema', max_evidence: 3 }),
    )
    act(() => view.container.querySelector<HTMLButtonElement>('[data-testid="extract-evidence-button"]')!.click())
    expect(onSelectEvidence).toHaveBeenCalledWith({ fieldName: 'field', evidence: response.result.field.evidence[0] })
  })
})
