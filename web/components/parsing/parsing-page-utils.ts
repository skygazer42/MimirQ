'use client'

import type { FileStatus } from '@/components/ui/file-queue-item'

import type { ParsedFile } from './parsing-types'

export type LibraryStatusBadge = {
  label: string
  cls: string
}

type ParsingWorkbenchTranslationGetter = (key: string) => string

export function countMarkdownHeadings(markdown: string) {
  const md = String(markdown || '').trim()
  if (!md) return 0
  return (md.match(/^#{1,6}\s+\S+/gm) || []).length
}

export function bumpParsingProgress(prev: ParsedFile[], fileId: string): ParsedFile[] {
  return prev.map((file) =>
    file.id === fileId && file.status === 'parsing'
      ? { ...file, progress: Math.min((file.progress || 0) + 5, 90) }
      : file
  )
}

export function mapBackendStatusToLibraryStatus(status?: string): FileStatus {
  const normalized = (status || '').toLowerCase()
  if (normalized === 'processing') return 'parsing'
  if (normalized === 'completed') return 'parsed'
  if (normalized === 'failed' || normalized === 'cancelled') return 'error'
  return 'pending'
}

export function getLibraryStatusBadge(
  t: ParsingWorkbenchTranslationGetter,
  status: FileStatus = 'pending'
): LibraryStatusBadge {
  switch (status) {
    case 'parsed':
      return { label: t('libraryStatus.parsed'), cls: 'bg-success/10 text-success dark:text-emerald-300 border-success/20' }
    case 'parsing':
      return { label: t('libraryStatus.parsing'), cls: 'bg-info/10 text-info border-info/20' }
    case 'error':
      return { label: t('libraryStatus.error'), cls: 'bg-destructive/10 text-destructive dark:text-red-300 border-destructive/20' }
    case 'pending':
    default:
      return { label: t('libraryStatus.pending'), cls: 'bg-warning/10 text-warning dark:text-amber-300 border-warning/20' }
  }
}
