import type { ParsedFileData } from '@/store/use-parsed-files-store'
import type { DocumentParsedContentResponse } from '@/types/backend'

export function hasParsedFileMemoryContent(
  file: Pick<ParsedFileData, 'contentLoaded' | 'markdownContent' | 'originalMarkdownContent'>,
): boolean {
  return (
    file.contentLoaded === true ||
    file.markdownContent.length > 0 ||
    (file.originalMarkdownContent !== undefined && file.originalMarkdownContent.length > 0)
  )
}

export function assertCompleteDocumentContent(
  content: Pick<DocumentParsedContentResponse, 'available' | 'markdown_truncated' | 'original_markdown_truncated'>,
): void {
  if (!content.available) throw new Error('解析正文暂不可用，请稍后重试')
  if (content.markdown_truncated || content.original_markdown_truncated) {
    throw new Error('解析正文超过读取范围，请在知识库详情中查看')
  }
}

type DocumentLibrarySnapshot = {
  knownFiles: ReadonlyMap<string, ParsedFileData>
  parsingResult: PromiseSettledResult<ParsedFileData[]>
  knowledgeResult: PromiseSettledResult<ParsedFileData[]>
}

export function mergeDocumentLibrary(current: ParsedFileData[], snapshot: DocumentLibrarySnapshot): ParsedFileData[] {
  if (snapshot.parsingResult.status === 'rejected' && snapshot.knowledgeResult.status === 'rejected') return current
  const currentById = new Map(current.map((file) => [file.id, file]))
  const nextById = new Map(currentById)
  const sources = [
    ['parsing_workspace', snapshot.parsingResult],
    ['knowledge_base', snapshot.knowledgeResult],
  ] as const
  for (const [source, result] of sources) {
    if (result.status === 'rejected') continue
    const remoteIds = new Set(result.value.map((file) => file.id))
    for (const file of current) {
      if (file.source !== source || snapshot.knownFiles.get(file.id) !== file) continue
      if (!remoteIds.has(file.id)) nextById.delete(file.id)
    }
    for (const file of result.value) {
      if (snapshot.knownFiles.get(file.id) !== currentById.get(file.id)) continue
      nextById.set(file.id, file)
    }
  }
  return [...nextById.values()]
}
