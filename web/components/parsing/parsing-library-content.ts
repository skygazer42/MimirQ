import { documentApi } from '@/lib/api/documents'
import {
  parsingApi,
  parsingPdfQualitySchema,
  parsingQualityGateSchema,
  type ParsingContentResponse,
  type ParsingElement,
} from '@/lib/api/parsing'
import { getDocContentFromCache } from '@/lib/doc-content-cache'
import { getParserLabel } from '@/lib/parser-options'
import { readPersistedParsingElements } from '@/lib/parsing-elements'
import { shouldRefreshParsingContentFromRemote } from '@/lib/parsing-run-restore'
import { assertCompleteDocumentContent, hasParsedFileMemoryContent } from '@/lib/document-library'
import type { ParsedFileData } from '@/store/use-parsed-files-store'

import {
  mapBackendStatusToLibraryStatus,
  normalizeParsingBackendCandidate,
  readParsingDurationSec,
} from './parsing-page-utils'
import type { FileStatus } from './parsing-types'

export type ParsingLibraryContent = {
  contentLoaded: true
  contentEdited?: boolean
  markdownContent: string
  originalMarkdownContent: string
  parser?: string
  parserBackend?: string
  durationSec?: number
  elements?: ParsingElement[]
  stats?: ParsingContentResponse['stats']
  pdfQuality?: ParsingContentResponse['pdf_quality']
  qualityGate?: ParsingContentResponse['quality_gate']
}

export type ParsingLibraryContentResult = {
  status: FileStatus
  error?: string
  content?: ParsingLibraryContent
}

export async function loadParsingLibraryContent(
  file: ParsedFileData,
  { signal, refresh = false }: { signal?: AbortSignal; refresh?: boolean } = {},
): Promise<ParsingLibraryContentResult> {
  signal?.throwIfAborted()
  let status = file.status ?? 'parsed'
  let error = file.error
  const isKnowledgeParsing =
    file.source === 'knowledge_base' && (file.status === 'pending' || file.status === 'parsing')
  if (isKnowledgeParsing) {
    const document = await documentApi.get(file.id, undefined, { signal })
    signal?.throwIfAborted()
    status = mapBackendStatusToLibraryStatus(document.status)
    error = document.error_message ?? undefined
  }

  const hasMemoryContent = hasParsedFileMemoryContent(file)
  const cached = hasMemoryContent ? null : await getDocContentFromCache(file.id)
  signal?.throwIfAborted()
  const hasSavedContent = hasMemoryContent || cached !== null
  const saved: ParsingLibraryContent = {
    contentLoaded: true,
    markdownContent: cached === null ? file.markdownContent : cached.markdownContent,
    originalMarkdownContent:
      cached === null
        ? (file.originalMarkdownContent ?? file.markdownContent)
        : (cached.originalMarkdownContent ?? cached.markdownContent),
    parser: file.parser,
    parserBackend: file.parserBackend,
    durationSec: file.durationSec,
    elements: file.elements,
    pdfQuality: file.pdfQuality,
    qualityGate: file.qualityGate,
    contentEdited: file.contentEdited,
  }
  if (status !== 'parsed') return hasSavedContent ? { status, error, content: saved } : { status, error }
  if (file.source === undefined) {
    if (!hasSavedContent) throw new Error('本地文档正文未找到，请重新导入文件')
    return { status, content: saved }
  }

  const useSavedContent =
    !refresh &&
    hasSavedContent &&
    (saved.contentEdited === true ||
      saved.originalMarkdownContent.length === 0 ||
      !shouldRefreshParsingContentFromRemote({
        fileType: file.fileType,
        originalMarkdownContent: saved.originalMarkdownContent,
      }))

  if (file.source === 'knowledge_base') {
    const content = await documentApi.getParsedContent(file.id, { max_chars: 2_000_000 }, { signal })
    signal?.throwIfAborted()
    if (!content.available && !isKnowledgeParsing && useSavedContent) return { status, content: saved }
    assertCompleteDocumentContent(content)
    const metadata = content.persisted_meta
    const backend =
      normalizeParsingBackendCandidate(metadata?.parser_backend) ??
      normalizeParsingBackendCandidate(metadata?.parser_backend_requested) ??
      file.parserBackend
    const durationSec = readParsingDurationSec(metadata?.parse_duration_sec) ?? file.durationSec
    return {
      status,
      content: {
        contentLoaded: true,
        markdownContent: content.markdown_content,
        originalMarkdownContent: content.original_markdown_content,
        parser: backend === undefined ? file.parser : getParserLabel(backend),
        parserBackend: backend,
        durationSec,
        elements: readPersistedParsingElements(metadata?.elements),
        pdfQuality: parsingPdfQualitySchema.parse(metadata?.pdf_quality),
        qualityGate: parsingQualityGateSchema.parse(metadata?.quality_gate),
      },
    }
  }

  if (useSavedContent) return { status, content: saved }

  const content = await parsingApi.getContent(file.id, { signal })
  signal?.throwIfAborted()
  const contentEdited = content.edited === true
  const remote: ParsingLibraryContent = {
    contentLoaded: true,
    markdownContent: content.markdown_content,
    originalMarkdownContent: content.original_markdown_content,
    parser: getParserLabel(content.parser_backend),
    parserBackend: content.parser_backend,
    durationSec: content.parse_duration_sec === null ? undefined : content.parse_duration_sec,
    elements: contentEdited ? undefined : (content.elements ?? undefined),
    stats: contentEdited ? undefined : content.stats,
    pdfQuality: contentEdited ? undefined : content.pdf_quality,
    qualityGate: contentEdited ? undefined : content.quality_gate,
    contentEdited,
  }

  // Layout recovery cannot replace the source of a different saved result.
  if (hasSavedContent && !refresh && remote.markdownContent !== saved.markdownContent) {
    return { status, content: saved }
  }
  return { status, content: remote }
}
