import type { PlatformIcon } from '@/components/icons'
import { File, FileMarkdown, FilePdf, FileCode, FileJson, FileSpreadsheet, FileText, FileType, FileImage, FileArchive, Presentation } from '@/components/icons'

import type { Document } from '@/types'

export type FileTypeMeta = {
  icon: PlatformIcon
  label: string
  color: string
  bg: string
  border: string
}

function fileMeta(icon: PlatformIcon, label: string, tone: string): FileTypeMeta {
  return { icon, label, color: `icon-ink-${tone}`, bg: `icon-surface-${tone}`, border: `icon-border-${tone}` }
}

export function getFileTypeMeta(doc: Pick<Document, 'filename' | 'file_type'>): FileTypeMeta {
  const explicit = String(doc.file_type || '').trim().toLowerCase()
  const fromName = String(doc.filename || '').trim().split('.').pop()?.toLowerCase()?.trim() || ''
  const ext = explicit || fromName

  switch (ext) {
    case 'pdf': return fileMeta(FilePdf, 'PDF', 'pdf')
    case 'doc':
    case 'docx': return fileMeta(FileType, ext.toUpperCase(), 'word')
    case 'ppt':
    case 'pptx': return fileMeta(Presentation, ext.toUpperCase(), 'slides')
    case 'xls':
    case 'xlsx':
    case 'csv': return fileMeta(FileSpreadsheet, ext.toUpperCase(), 'sheet')
    case 'markdown':
    case 'md': return fileMeta(FileMarkdown, 'MD', 'neutral')
    case 'txt': return fileMeta(FileText, 'TXT', 'neutral')
    case 'json': return fileMeta(FileJson, 'JSON', 'code')
    case 'html':
    case 'htm': return fileMeta(FileCode, 'HTML', 'code')
    case 'js':
    case 'ts':
    case 'jsx':
    case 'tsx':
    case 'py':
    case 'yaml':
    case 'yml':
    case 'toml':
    case 'xml':
    case 'css':
    case 'sql':
    case 'java':
    case 'go':
    case 'rs': return fileMeta(FileCode, ext.toUpperCase(), 'code')
    case 'png':
    case 'jpg':
    case 'jpeg':
    case 'webp':
    case 'gif': return fileMeta(FileImage, ext.toUpperCase(), 'media')
    case 'zip':
    case 'rar':
    case '7z': return fileMeta(FileArchive, ext.toUpperCase(), 'code')
    default: return fileMeta(File, ext ? ext.toUpperCase() : 'FILE', 'neutral')
  }
}
