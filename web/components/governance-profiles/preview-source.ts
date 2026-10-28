import { documentApi, parsingApi } from '@/lib/api'
import { getAuthCacheScope } from '@/lib/auth-storage'
import { getDocContentFromCache } from '@/lib/doc-content-cache'
import { useParsedFiles, type ParsedFileData } from '@/store/use-parsed-files-store'
import type { Document } from '@/types'

export type PreviewDocument = {
  id: string
  filename: string
  fileType: string
  source: 'parsing_workspace' | 'knowledge_base'
  remote?: boolean
}

export type PreviewSource = {
  scope: string
  document: PreviewDocument | null
  manualInput: string
  manualFormat: 'markdown' | 'html'
}

export function emptyPreviewSource(): PreviewSource {
  return { scope: getAuthCacheScope(), document: null, manualInput: '', manualFormat: 'markdown' }
}

export function localPreviewDocument(file: ParsedFileData): PreviewDocument | null {
  if (file.status && file.status !== 'parsed') return null
  if (!file.status && !file.markdownContent && !file.originalMarkdownContent && !file.governanceStatus) return null
  return { id: file.id, filename: file.filename, fileType: file.fileType, source: file.source || 'parsing_workspace' }
}

export function remotePreviewDocument(file: Document): PreviewDocument {
  return { id: file.id, filename: file.filename, fileType: file.file_type, source: 'parsing_workspace', remote: true }
}

function sourceContent(markdown: string, original?: string | null) {
  return { text: original || markdown, origin: original ? '解析原文' : '已保存正文' }
}

export async function readPreviewDocument(document: PreviewDocument, scope: string) {
  const assertScope = () => { if (getAuthCacheScope() !== scope) throw new Error('账户已切换，请重新选择文档') }
  assertScope()
  if (document.remote) {
    const response = await parsingApi.getContent(document.id)
    assertScope()
    return sourceContent(response.markdown_content || '', response.original_markdown_content)
  }
  const local = useParsedFiles.getState().files.find(file => file.id === document.id)
  if (local?.originalMarkdownContent || local?.markdownContent) {
    return sourceContent(local.markdownContent, local.originalMarkdownContent)
  }
  const cached = await getDocContentFromCache(document.id, scope).catch(() => null)
  assertScope()
  if (cached && (cached.originalMarkdownContent || cached.markdownContent)) {
    return sourceContent(cached.markdownContent, cached.originalMarkdownContent)
  }
  const response = document.source === 'knowledge_base'
    ? await documentApi.getParsedContent(document.id, { max_chars: 2_000_000 })
    : await parsingApi.getContent(document.id)
  assertScope()
  return sourceContent(response.markdown_content || '', response.original_markdown_content)
}
