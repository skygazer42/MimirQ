// @vitest-environment jsdom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderHook, waitForAssertion } from '@/test/hook-harness'
import type { ParsedFileData } from '@/store/use-parsed-files-store'

const parsingApiMocks = vi.hoisted(() => ({
  delete: vi.fn(),
}))
const documentApiMocks = vi.hoisted(() => ({
  delete: vi.fn(),
}))

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => key,
}))

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}))

vi.mock('@/lib/api', () => ({
  documentApi: documentApiMocks,
  parsingApi: parsingApiMocks,
}))

import { useParsingQueueActions } from './use-parsing-queue-actions'

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  })

  return {
    queryClient,
    wrapper({ children }: { children: React.ReactNode }) {
      return React.createElement(QueryClientProvider, { client: queryClient }, children)
    },
  }
}

function makeLibraryFile(overrides: Partial<ParsedFileData> = {}): ParsedFileData {
  return {
    id: 'lib-1',
    filename: 'imagenet-localization.pdf',
    fileType: 'pdf',
    fileSize: 1024,
    markdownContent: '',
    originalMarkdownContent: '',
    parsedAt: new Date().toISOString(),
    parser: 'MinerU',
    folderId: 'root',
    status: 'parsed',
    ...overrides,
  }
}

describe('useParsingQueueActions behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('evicts deleted parsing documents from query cache so merged tree files do not reappear', async () => {
    parsingApiMocks.delete.mockResolvedValue(undefined)

    const libraryFile = makeLibraryFile()
    const siblingFile = makeLibraryFile({ id: 'lib-2', filename: 'notes.md' })
    const files = [
      {
        id: 'queue-1',
        libraryId: 'lib-1',
        folderId: 'root',
        name: 'imagenet-localization.pdf',
        size: 1024,
        status: 'parsed' as const,
        markdownContent: null,
        parserBackend: 'mineru',
        parserLabel: 'MinerU',
        createdAt: Date.now(),
        file: new File(['pdf'], 'imagenet-localization.pdf', { type: 'application/pdf' }),
      },
    ]

    const { queryClient, wrapper } = createWrapper()
    queryClient.setQueryData(['parsing', 'library-documents'], [libraryFile, siblingFile])
    queryClient.setQueryData(['parsing', 'library-content', 'lib-1'], {
      markdownContent: '# cached',
    })

    const hook = renderHook(
      () =>
        useParsingQueueActions({
          activeFileId: 'queue-1',
          activeLibraryFileId: null,
          cancelParse: vi.fn(),
          files,
          libraryFiles: [libraryFile, siblingFile],
          moveFolder: vi.fn(),
          removeLibraryCaches: vi.fn(),
          removeParsedFile: vi.fn(),
          setActiveFileId: vi.fn(),
          setActiveLibraryFileId: vi.fn(),
          setDragOverFolderId: vi.fn(),
          setFiles: vi.fn(),
          updateParsedFile: vi.fn(),
        }),
      { wrapper }
    )

    act(() => {
      hook.result.current.removeFile('queue-1')
    })

    await waitForAssertion(() => {
      expect(parsingApiMocks.delete).toHaveBeenCalledWith('lib-1')
    })

    expect(queryClient.getQueryData(['parsing', 'library-documents'])).toEqual([siblingFile])
    expect(queryClient.getQueryData(['parsing', 'library-content', 'lib-1'])).toBeUndefined()

    hook.unmount()
    queryClient.clear()
  })

  it('deletes knowledge-base documents through the document API instead of only clearing local caches', async () => {
    documentApiMocks.delete.mockResolvedValue(undefined)

    const libraryFile = makeLibraryFile({
      id: 'kb-doc-1',
      filename: '根目录知识库文件.txt',
      source: 'knowledge_base',
    })
    const siblingFile = makeLibraryFile({
      id: 'kb-doc-2',
      filename: '保留文件.txt',
      source: 'knowledge_base',
    })
    const { queryClient, wrapper } = createWrapper()
    queryClient.setQueryData(['parsing', 'library-documents'], [libraryFile, siblingFile])
    queryClient.setQueryData(['parsing', 'library-content', 'kb-doc-1'], {
      markdownContent: '# cached',
    })

    const removeParsedFile = vi.fn()
    const removeLibraryCaches = vi.fn()
    const setActiveLibraryFileId = vi.fn()
    const hook = renderHook(
      () =>
        useParsingQueueActions({
          activeFileId: null,
          activeLibraryFileId: 'kb-doc-1',
          cancelParse: vi.fn(),
          files: [],
          libraryFiles: [libraryFile, siblingFile],
          moveFolder: vi.fn(),
          removeLibraryCaches,
          removeParsedFile,
          setActiveFileId: vi.fn(),
          setActiveLibraryFileId,
          setDragOverFolderId: vi.fn(),
          setFiles: vi.fn(),
          updateParsedFile: vi.fn(),
        }),
      { wrapper }
    )

    act(() => {
      hook.result.current.removeFile('kb-doc-1')
    })

    await waitForAssertion(() => {
      expect(documentApiMocks.delete).toHaveBeenCalledWith('kb-doc-1')
    })

    expect(parsingApiMocks.delete).not.toHaveBeenCalled()
    expect(queryClient.getQueryData(['parsing', 'library-documents'])).toEqual([siblingFile])
    expect(queryClient.getQueryData(['parsing', 'library-content', 'kb-doc-1'])).toBeUndefined()
    expect(removeParsedFile).toHaveBeenCalledWith('kb-doc-1')
    expect(removeLibraryCaches).toHaveBeenCalledWith('kb-doc-1')
    expect(setActiveLibraryFileId).toHaveBeenCalledWith(null)

    hook.unmount()
    queryClient.clear()
  })
})
