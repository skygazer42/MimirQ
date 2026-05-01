'use client'

import type { ParseCompareRun } from '@/components/parsing/parse-compare-dialog'
import type { ParsingElement } from '@/lib/api/parsing'
import type { FileQueueItemData } from '@/components/ui/file-queue-item'
import type { ParsingBlock } from '@/lib/parsing-positions'

export interface ParseRun extends ParseCompareRun {
  parserBackend: string
  parserLabel: string
  rawMarkdown: string
  cleanedMarkdown: string
  createdAt: number
  blocks: ParsingBlock[]
  elements?: ParsingElement[]
  pdfQuality?: unknown
  qualityGate?: unknown
}

export interface ParseFailureDiagnostics {
  file_type?: string
  parser_backend_requested?: string
  parser_backend?: string
  error_type?: string
  error_message?: string
  pdf_sample?: {
    page_count?: number
    is_scanned?: boolean
    samples?: { page: number; text_chars: number; excerpt: string }[]
  }
  suggested_backends?: string[]
}

export interface ParsedFile extends FileQueueItemData {
  file: File
  folderId: string
  sourcePath?: string
  markdownContent: string | null
  parserBackend: string
  parserLabel: string
  libraryId?: string
  librarySource?: 'parsing_workspace' | 'knowledge_base'
  runs?: ParseRun[]
  activeRunId?: string
  parseStartTime?: number
  createdAt?: number
  stats?: {
    charCount: number
    lineCount: number
    headingCount: number
    pageCount?: number
    tableCount?: number
    imageCount?: number
    blockCount?: number
  }
  elements?: ParsingElement[]
  pdfQuality?: unknown
  qualityGate?: unknown
  parseDiagnostics?: ParseFailureDiagnostics
}
