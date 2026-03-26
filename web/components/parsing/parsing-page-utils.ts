'use client'

import type { FileStatus } from '@/components/ui/file-queue-item'

import type { ParsedFile } from './parsing-types'

export type LibraryStatusBadge = {
  label: string
  cls: string
}

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

export function getLibraryStatusBadge(status: FileStatus = 'pending'): LibraryStatusBadge {
  switch (status) {
    case 'parsed':
      return { label: '已解析', cls: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/20' }
    case 'parsing':
      return { label: '解析中', cls: 'bg-sky-500/10 text-sky-700 dark:text-sky-300 border-sky-500/20' }
    case 'error':
      return { label: '失败', cls: 'bg-red-500/10 text-red-700 dark:text-red-300 border-red-500/20' }
    case 'pending':
    default:
      return { label: '待解析', cls: 'bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/20' }
  }
}
