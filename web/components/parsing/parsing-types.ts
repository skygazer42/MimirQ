import { z } from 'zod'
import type { ParsingElement } from '@/lib/api/parsing'
import type { ParsingBlock } from '@/lib/parsing-positions'

export type ParsingLibrarySourceStatus = 'unknown' | 'available' | 'missing'
export type FileStatus = 'pending' | 'parsing' | 'parsed' | 'error'

export type ParsingStatistics = {
  charCount: number
  lineCount: number
  headingCount: number
  pageCount?: number
  tableCount?: number
  imageCount?: number
  blockCount?: number
}

export type ParseRun = {
  id: string
  parserBackend: string
  parserLabel: string
  rawMarkdown: string
  cleanedMarkdown: string
  createdAt: number
  blocks: ParsingBlock[]
  elements?: ParsingElement[]
  pdfQuality?: unknown
  qualityGate?: unknown
  stats?: ParsingStatistics
  durationSec?: number
  contentEdited?: boolean
}

export const parseFailureDiagnosticsSchema = z.object({
  file_type: z.string().optional(),
  parser_backend_requested: z.string().optional(),
  parser_backend: z.string().optional(),
  error_type: z.string().nullable().optional(),
  error_message: z.string().optional(),
  pdf_sample: z
    .object({
      page_count: z.number().int().optional(),
      is_scanned: z.boolean().optional(),
      samples: z
        .array(z.object({ page: z.number().int(), text_chars: z.number().int(), excerpt: z.string() }))
        .optional(),
    })
    .optional(),
  suggested_backends: z.array(z.string()).optional(),
})

type ParseFailureDiagnostics = z.infer<typeof parseFailureDiagnosticsSchema>

export type ParsedFile = {
  id: string
  name: string
  size: number
  status: FileStatus
  progress?: number
  parser?: string
  chunkStrategyLabel?: string
  error?: string
  duration?: number
  pageCount?: number
  folderPathLabel?: string
  file: File
  folderId: string
  sourcePath?: string
  markdownContent: string | null
  contentEdited?: boolean
  parserBackend: string
  parserLabel: string
  datasetId?: string | null
  datasetName?: string | null
  libraryId?: string
  librarySource?: 'parsing_workspace' | 'knowledge_base'
  governanceStatus?: 'draft' | 'ready' | 'submitted'
  runs?: ParseRun[]
  activeRunId?: string
  savedRunId?: string
  parseStartTime?: number
  createdAt?: number
  stats?: ParsingStatistics
  elements?: ParsingElement[]
  pdfQuality?: unknown
  qualityGate?: unknown
  parseDiagnostics?: ParseFailureDiagnostics
}
