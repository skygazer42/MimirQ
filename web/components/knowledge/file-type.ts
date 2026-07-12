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
        color: 'text-destructive dark:text-red-400',
        bg: 'bg-destructive/10 dark:bg-red-900/20',
        border: 'border-destructive/30 dark:border-red-500/30',
      }
    case 'docx':
      return {
        icon: FileType,
        label: 'DOCX',
        color: 'text-primary',
        bg: 'bg-primary/10',
        border: 'border-primary/30',
      }
    case 'doc':
      return {
        icon: FileType,
        label: 'DOC',
        color: 'text-primary dark:text-indigo-400',
        bg: 'bg-primary/10 dark:bg-indigo-900/20',
        border: 'border-primary/30 dark:border-indigo-500/30',
      }
    case 'ppt':
    case 'pptx':
      return {
        icon: Presentation,
        label: ext.toUpperCase(),
        color: 'text-destructive dark:text-rose-300',
        bg: 'bg-destructive/10 dark:bg-rose-900/20',
        border: 'border-destructive/30 dark:border-rose-500/30',
      }
    case 'xlsx':
    case 'xls':
      return {
        icon: FileSpreadsheet,
        label: ext.toUpperCase(),
        color: 'text-success dark:text-emerald-300',
        bg: 'bg-success/10 dark:bg-emerald-900/20',
        border: 'border-success/30 dark:border-emerald-500/30',
      }
    case 'csv':
      return {
        icon: FileSpreadsheet,
        label: 'CSV',
        color: 'text-success dark:text-teal-300',
        bg: 'bg-success/10 dark:bg-teal-900/20',
        border: 'border-success/30 dark:border-teal-500/30',
      }
    case 'md':
      return {
        icon: FileCode,
        label: 'MD',
        color: 'text-accent dark:text-purple-300',
        bg: 'bg-accent/10 dark:bg-purple-900/20',
        border: 'border-accent/30 dark:border-purple-500/30',
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
        color: 'text-warning dark:text-amber-300',
        bg: 'bg-warning/10 dark:bg-amber-900/20',
        border: 'border-warning/30 dark:border-amber-500/30',
      }
    case 'html':
    case 'htm':
      return {
        icon: FileCode,
        label: 'HTML',
        color: 'text-warning dark:text-orange-300',
        bg: 'bg-warning/10 dark:bg-orange-900/20',
        border: 'border-warning/30 dark:border-orange-500/30',
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
