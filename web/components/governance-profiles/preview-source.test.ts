import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ParsedFileData } from '@/store/use-parsed-files-store'

const mocks = vi.hoisted(() => ({
  scope: 'tenant:member',
  files: [] as ParsedFileData[],
  cache: vi.fn(),
  parsingContent: vi.fn(),
  knowledgeContent: vi.fn(),
}))
vi.mock('@/lib/api', () => ({ parsingApi: { getContent: mocks.parsingContent }, documentApi: { getParsedContent: mocks.knowledgeContent } }))
vi.mock('@/lib/auth-storage', () => ({ getAuthCacheScope: () => mocks.scope }))
vi.mock('@/lib/doc-content-cache', () => ({ getDocContentFromCache: mocks.cache }))
vi.mock('@/store/use-parsed-files-store', () => ({ useParsedFiles: { getState: () => ({ files: mocks.files }) } }))

import { localPreviewDocument, readPreviewDocument, type PreviewDocument } from './preview-source'

const document: PreviewDocument = { id: 'parsed-doc', filename: 'document.pdf', fileType: 'pdf', source: 'parsing_workspace' }
const file = (overrides: Partial<ParsedFileData> = {}): ParsedFileData => ({ id: document.id, filename: document.filename, fileType: 'pdf', fileSize: 100, markdownContent: '保存稿', originalMarkdownContent: '解析原文', parsedAt: '2026-10-23T01:00:00Z', parser: 'text', status: 'parsed', ...overrides })

beforeEach(() => {
  vi.resetAllMocks()
  mocks.scope = 'tenant:member'
  mocks.files = []
  mocks.cache.mockResolvedValue(null)
})

describe('parsed document preview sources', () => {
  it('lists ready documents, including hydrated entries without inline content, and excludes unfinished documents', () => {
    expect(localPreviewDocument(file({ markdownContent: '', originalMarkdownContent: '' }))).toMatchObject({ id: document.id })
    for (const status of ['pending', 'parsing', 'error'] as const) expect(localPreviewDocument(file({ status }))).toBeNull()
  })

  it('uses the local parsed original rather than the later saved cleaned text', async () => {
    mocks.files = [file()]
    await expect(readPreviewDocument(document, mocks.scope)).resolves.toEqual({ text: '解析原文', origin: '解析原文' })
    expect(mocks.cache).not.toHaveBeenCalled()
    expect(mocks.parsingContent).not.toHaveBeenCalled()
  })

  it('re-reads persisted parsing documents from the server rather than stale local copies', async () => {
    mocks.files = [file({ originalMarkdownContent: '上次解析的缓存' })]
    mocks.parsingContent.mockResolvedValue({ markdown_content: '保存稿', original_markdown_content: '重新解析后的原文' })
    await expect(readPreviewDocument({ ...document, remote: true }, mocks.scope)).resolves.toEqual({ text: '重新解析后的原文', origin: '解析原文' })
    expect(mocks.cache).not.toHaveBeenCalled()
  })

  it('reads a hydrated document from the current account cache', async () => {
    mocks.files = [file({ markdownContent: '', originalMarkdownContent: '' })]
    mocks.cache.mockResolvedValue({ markdownContent: '已清洗正文', originalMarkdownContent: '缓存中的解析原文' })
    await expect(readPreviewDocument(document, mocks.scope)).resolves.toEqual({ text: '缓存中的解析原文', origin: '解析原文' })
    expect(mocks.cache).toHaveBeenCalledWith(document.id, 'tenant:member')
    expect(mocks.parsingContent).not.toHaveBeenCalled()
  })

  it('falls back to the parsing API when browser storage is unavailable and labels missing original content honestly', async () => {
    mocks.cache.mockRejectedValue(new Error('IndexedDB unavailable'))
    mocks.parsingContent.mockResolvedValue({ markdown_content: '仅有保存正文', original_markdown_content: '' })
    await expect(readPreviewDocument(document, mocks.scope)).resolves.toEqual({ text: '仅有保存正文', origin: '已保存正文' })
    expect(mocks.parsingContent).toHaveBeenCalledWith(document.id)
  })

  it('uses the knowledge content endpoint for documents already in the governance library', async () => {
    mocks.knowledgeContent.mockResolvedValue({ markdown_content: '保存稿', original_markdown_content: '知识库解析原文' })
    await expect(readPreviewDocument({ ...document, source: 'knowledge_base' }, mocks.scope)).resolves.toEqual({ text: '知识库解析原文', origin: '解析原文' })
    expect(mocks.knowledgeContent).toHaveBeenCalledWith(document.id, { max_chars: 2_000_000 })
    expect(mocks.parsingContent).not.toHaveBeenCalled()
  })

  it('rejects cached content returned after an account switch', async () => {
    mocks.cache.mockImplementation(async () => { mocks.scope = 'tenant:other'; return { markdownContent: '旧账户正文' } })
    await expect(readPreviewDocument(document, 'tenant:member')).rejects.toThrow('账户已切换')
    expect(mocks.parsingContent).not.toHaveBeenCalled()
  })

  it('rejects a remote response returned after an account switch', async () => {
    mocks.parsingContent.mockImplementation(async () => { mocks.scope = 'tenant:other'; return { markdown_content: '旧账户正文' } })
    await expect(readPreviewDocument(document, 'tenant:member')).rejects.toThrow('账户已切换')
  })
})
