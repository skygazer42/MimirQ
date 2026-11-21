import { documentApi, parsingApi } from '@/lib/api'
import type { ApiRequestOptions } from '@/lib/api/core'
import { getAuthCacheScope } from '@/lib/auth-storage'
import { getDocContentFromCache } from '@/lib/doc-content-cache'
import { hasParsedFileMemoryContent } from '@/lib/document-library'
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
  if (file.status !== undefined && file.status !== 'parsed') return null
  if (file.status === undefined && file.governanceStatus === undefined && !hasParsedFileMemoryContent(file)) return null
  return { id: file.id, filename: file.filename, fileType: file.fileType, source: file.source ?? 'parsing_workspace' }
}

export function remotePreviewDocument(file: Document): PreviewDocument {
  return { id: file.id, filename: file.filename, fileType: file.file_type, source: 'parsing_workspace', remote: true }
}

function sourceContent(markdown: string, original?: string | null) {
  if (original == null || original === '') return { text: markdown, origin: '已保存正文' }
  return { text: original, origin: '解析原文' }
}

export async function readPreviewDocument(
  document: PreviewDocument,
  scope: string,
  ...requestOptions: [options?: ApiRequestOptions]
) {
  const assertScope = () => {
    requestOptions[0]?.signal?.throwIfAborted()
    if (getAuthCacheScope() !== scope) throw new Error('账户已切换，请重新选择文档')
  }
  assertScope()

  if (!document.remote) {
    const local = useParsedFiles.getState().files.find((file) => file.id === document.id)
    if (local !== undefined && hasParsedFileMemoryContent(local)) {
      return sourceContent(local.markdownContent, local.originalMarkdownContent)
    }
    const cached = await getDocContentFromCache(document.id, scope).catch(() => null)
    assertScope()
    if (cached !== null) return sourceContent(cached.markdownContent, cached.originalMarkdownContent)
  }

  const response =
    document.source === 'knowledge_base'
      ? await documentApi.getParsedContent(document.id, { max_chars: 2_000_000 }, ...requestOptions)
      : await parsingApi.getContent(document.id, ...requestOptions)
  assertScope()
  return sourceContent(response.markdown_content, response.original_markdown_content)
}
