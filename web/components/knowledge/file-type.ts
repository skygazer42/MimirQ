import type { LucideIcon } from 'lucide-react'
import { File, FileCode, FileSpreadsheet, FileText, FileType, Presentation } from 'lucide-react'

import type { Document } from '@/types'

export type FileTypeMeta = {
  icon: LucideIcon
  label: string
  color: string
  bg: string
  border: string
}

export function getFileTypeMeta(doc: Pick<Document, 'filename' | 'file_type'>): FileTypeMeta {
  const explicit = String(doc.file_type || '').trim().toLowerCase()
  const fromName =
    String(doc.filename || '')
      .trim()
      .split('.')
      .pop()
      ?.toLowerCase()
      ?.trim() || ''
  const ext = explicit || fromName

  const base = {
    border: 'border-border/60',
  }

  switch (ext) {
    case 'pdf':
      return {
        icon: FileText,
        label: 'PDF',
        color: 'text-red-600 dark:text-red-400',
        bg: 'bg-red-50 dark:bg-red-900/20',
        border: 'border-red-200/60 dark:border-red-500/30',
      }
    case 'docx':
      return {
        icon: FileType,
        label: 'DOCX',
        color: 'text-blue-600 dark:text-blue-400',
        bg: 'bg-blue-50 dark:bg-blue-900/20',
        border: 'border-blue-200/60 dark:border-blue-500/30',
      }
    case 'doc':
      return {
        icon: FileType,
        label: 'DOC',
        color: 'text-indigo-600 dark:text-indigo-400',
        bg: 'bg-indigo-50 dark:bg-indigo-900/20',
        border: 'border-indigo-200/60 dark:border-indigo-500/30',
      }
    case 'ppt':
    case 'pptx':
      return {
        icon: Presentation,
        label: ext.toUpperCase(),
        color: 'text-rose-700 dark:text-rose-300',
        bg: 'bg-rose-50 dark:bg-rose-900/20',
        border: 'border-rose-200/60 dark:border-rose-500/30',
      }
    case 'xlsx':
    case 'xls':
      return {
        icon: FileSpreadsheet,
        label: ext.toUpperCase(),
        color: 'text-emerald-700 dark:text-emerald-300',
        bg: 'bg-emerald-50 dark:bg-emerald-900/20',
        border: 'border-emerald-200/60 dark:border-emerald-500/30',
      }
    case 'csv':
      return {
        icon: FileSpreadsheet,
        label: 'CSV',
        color: 'text-teal-700 dark:text-teal-300',
        bg: 'bg-teal-50 dark:bg-teal-900/20',
        border: 'border-teal-200/60 dark:border-teal-500/30',
      }
    case 'md':
      return {
        icon: FileCode,
        label: 'MD',
        color: 'text-purple-700 dark:text-purple-300',
        bg: 'bg-purple-50 dark:bg-purple-900/20',
        border: 'border-purple-200/60 dark:border-purple-500/30',
      }
    case 'txt':
      return {
        icon: FileText,
        label: 'TXT',
        color: 'text-muted-foreground',
        bg: 'bg-muted/40',
        border: base.border,
      }
    case 'json':
      return {
        icon: FileCode,
        label: 'JSON',
        color: 'text-amber-700 dark:text-amber-300',
        bg: 'bg-amber-50 dark:bg-amber-900/20',
        border: 'border-amber-200/60 dark:border-amber-500/30',
      }
    case 'html':
    case 'htm':
      return {
        icon: FileCode,
        label: 'HTML',
        color: 'text-orange-700 dark:text-orange-300',
        bg: 'bg-orange-50 dark:bg-orange-900/20',
        border: 'border-orange-200/60 dark:border-orange-500/30',
      }
    default:
      return {
        icon: File,
        label: ext ? ext.toUpperCase() : 'FILE',
        color: 'text-muted-foreground',
        bg: 'bg-muted/40',
        border: base.border,
      }
  }
}

