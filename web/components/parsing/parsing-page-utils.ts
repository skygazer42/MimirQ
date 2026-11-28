import type { ParsingContentResponse } from '@/lib/api/parsing'

import type { FileStatus, ParsedFile, ParseRun, ParsingStatistics } from './parsing-types'

export function getActiveParsingRun(file: ParsedFile): ParseRun | undefined {
  if (file.activeRunId === undefined) return file.runs?.at(-1)
  return file.runs?.find((run) => run.id === file.activeRunId)
}

export function buildParsingStatistics(
  markdown: string,
  blockCount: number,
  reported?: ParsingContentResponse['stats'],
): ParsingStatistics {
  return {
    charCount: markdown.length,
    lineCount: markdown.split('\n').length,
    headingCount: countMarkdownHeadings(markdown),
    pageCount: reported?.page_count,
    tableCount: reported?.table_count,
    imageCount: reported?.image_count,
    blockCount,
  }
}

export function getParsingRunStatistics(run: ParseRun): ParsingStatistics {
  return run.stats === undefined ? buildParsingStatistics(run.cleanedMarkdown, run.blocks.length) : run.stats
}

export function normalizeParsingBackendCandidate(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const candidate = value.trim()
  return candidate.length === 0 ? undefined : candidate
}

export function readParsingDurationSec(value: unknown): number | undefined {
  if (typeof value !== 'number' && typeof value !== 'string') return undefined
  if (typeof value === 'string' && value.trim() === '') return undefined
  const durationSec = Number(value)
  return Number.isFinite(durationSec) ? durationSec : undefined
}

function countMarkdownHeadings(markdown: string) {
  const headings = markdown.trim().match(/^#{1,6}\s+\S+/gm)
  return headings === null ? 0 : headings.length
}

export function bumpParsingProgress(files: ParsedFile[], fileId: string): ParsedFile[] {
  return files.map((file) =>
    file.id === fileId && file.status === 'parsing'
      ? { ...file, progress: Math.min((file.progress ?? 0) + 5, 90) }
      : file,
  )
}

export function mapBackendStatusToLibraryStatus(status?: string): FileStatus {
  const normalized = status?.toLowerCase()
  if (normalized === 'processing') return 'parsing'
  if (normalized === 'completed') return 'parsed'
  if (normalized === 'failed' || normalized === 'cancelled') return 'error'
  return 'pending'
}
