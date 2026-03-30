'use client'

import { cn, formatFileSize } from '@/lib/utils'
import {
  FileText,
  FileSpreadsheet,
  FileType,
  File,
  Presentation,
  Loader2,
  CheckCircle,
  XCircle,
  Trash2,
  RotateCcw,
  Clock,
} from 'lucide-react'
import { useTranslations } from 'next-intl'

// 文件类型配置
const FILE_TYPE_CONFIG: Record<
  string,
  { icon: typeof FileText; color: string; bg: string }
> = {
  pdf: { icon: FileText, color: 'text-red-600 dark:text-red-400', bg: 'bg-red-50 dark:bg-red-900/20' },
  pptx: { icon: Presentation, color: 'text-orange-700 dark:text-orange-400', bg: 'bg-orange-50 dark:bg-orange-900/20' },
  ppt: { icon: Presentation, color: 'text-orange-700 dark:text-orange-400', bg: 'bg-orange-50 dark:bg-orange-900/20' },
  xlsx: { icon: FileSpreadsheet, color: 'text-emerald-700 dark:text-emerald-400', bg: 'bg-emerald-50 dark:bg-emerald-900/20' },
  xls: { icon: FileSpreadsheet, color: 'text-emerald-700 dark:text-emerald-400', bg: 'bg-emerald-50 dark:bg-emerald-900/20' },
  docx: { icon: FileType, color: 'text-blue-700 dark:text-blue-400', bg: 'bg-blue-50 dark:bg-blue-900/20' },
  doc: { icon: FileType, color: 'text-blue-700 dark:text-blue-400', bg: 'bg-blue-50 dark:bg-blue-900/20' },
  txt: { icon: File, color: 'text-slate-600 dark:text-slate-300', bg: 'bg-slate-50 dark:bg-slate-800/60' },
  md: { icon: FileText, color: 'text-purple-700 dark:text-purple-300', bg: 'bg-purple-50 dark:bg-purple-900/20' },
}

export type FileStatus = 'pending' | 'parsing' | 'parsed' | 'error'

export interface FileQueueItemData {
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
  sourcePath?: string
}

interface FileQueueItemProps {
  file: FileQueueItemData
  isActive?: boolean
  draggable?: boolean
  onDragStart?: (e: React.DragEvent<HTMLElement>) => void
  onClick?: () => void
  onRemove?: () => void
  onRetry?: () => void
}

export function FileQueueItem({
  file,
  isActive = false,
  draggable = false,
  onDragStart,
  onClick,
  onRemove,
  onRetry,
}: Readonly<FileQueueItemProps>) {
  const t = useTranslations('CommonUi')
  const ext = file.name.split('.').pop()?.toLowerCase() || 'txt'
  const config = FILE_TYPE_CONFIG[ext] || FILE_TYPE_CONFIG.txt
  const Icon = config.icon
  const progressPct =
    file.progress == null || !Number.isFinite(Number(file.progress))
      ? 0
      : Math.max(0, Math.min(100, Number(file.progress)))

  const getStatusContent = () => {
    switch (file.status) {
      case 'pending':
        return (
          <div className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400">
            <Clock className="w-3 h-3" />
            <span>{t("fileQueueItem.pending")}</span>
          </div>
        )
      case 'parsing':
        return (
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5 text-xs text-info">
              <Loader2 className="w-3 h-3 animate-spin motion-reduce:animate-none" />
              <span>{t("fileQueueItem.parsing")} {file.progress == null ? '' : `${progressPct}%`}</span>
            </div>
            {file.progress !== undefined && (
              <div className="w-full h-1.5 bg-secondary rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary rounded-full origin-left transition-transform duration-200 ease-out motion-reduce:transition-none"
                  style={{ transform: `scaleX(${progressPct / 100})` }}
                />
              </div>
            )}
          </div>
        )
      case 'parsed':
        return (
          <div className="flex items-center gap-2 text-xs">
            <span className="flex items-center gap-1 text-emerald-700 dark:text-emerald-400">
              <CheckCircle className="w-3 h-3" />
              {t("fileQueueItem.parsed")}
            </span>
            {file.parser && (
              <span className="text-slate-500 dark:text-slate-400">· {file.parser}</span>
            )}
            {file.chunkStrategyLabel && (
              <span className="text-slate-500 dark:text-slate-400">· {file.chunkStrategyLabel}</span>
            )}
            {typeof file.duration === 'number' && Number.isFinite(file.duration) ? (
              <span className="text-slate-500 dark:text-slate-400">· {file.duration}s</span>
            ) : null}
          </div>
        )
      case 'error':
        return (
          <span className="flex items-center gap-1 text-xs text-red-700 dark:text-red-400">
            <XCircle className="w-3 h-3" />
            {t("fileQueueItem.error")}
          </span>
        )
    }
  }

  const fileContent = (
    <>
      <div className={cn('p-2.5 rounded-lg flex-shrink-0', config.bg)}>
        <Icon className={cn('w-5 h-5', config.color)} />
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
          {file.name}
        </p>

        {(file.folderPathLabel || file.sourcePath) && (
          <p
            className="mt-0.5 text-xs text-slate-500 dark:text-slate-400 truncate"
            title={[file.folderPathLabel, file.sourcePath].filter(Boolean).join(' · ')}
          >
            {file.folderPathLabel ? `${t("fileQueueItem.folderLabel")}${file.folderPathLabel}` : ''}
            {file.sourcePath ? ` · ${t("fileQueueItem.sourcePathLabel")}${file.sourcePath}` : ''}
          </p>
        )}

        <div className="flex items-center gap-2 mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          <span>{formatFileSize(file.size)}</span>
          {file.pageCount && (
            <>
              <span>·</span>
              <span>{t("fileQueueItem.pages", { count: String(file.pageCount) })}</span>
            </>
          )}
        </div>

        <div className="mt-2">{getStatusContent()}</div>
      </div>
    </>
  )

  return (
    <div
      className={cn(
        'group p-3 rounded-xl border cursor-pointer transition-colors duration-200 motion-reduce:transition-none',
        isActive
          ? 'bg-info/10 border-info/25 shadow-sm dark:shadow-none'
          : 'bg-card border-border hover:border-info/25 hover:bg-muted/40'
      )}
    >
      <div className="flex items-start gap-2">
        {onClick ? (
          <button
            type="button"
            className="flex min-w-0 flex-1 items-start gap-3 rounded-lg text-left focus-ring"
            onClick={onClick}
            draggable={draggable}
            onDragStart={onDragStart}
          >
            {fileContent}
          </button>
        ) : (
          <div className="flex min-w-0 flex-1 items-start gap-3">
            {fileContent}
          </div>
        )}

        {(onRetry || onRemove) && (
          <div className="flex shrink-0 items-start gap-1">
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="flex items-center gap-1 text-xs text-info hover:text-info/90 focus-ring rounded px-1.5 py-1"
              >
                <RotateCcw className="w-3 h-3" />
                {t("fileQueueItem.retry")}
              </button>
            )}
            {onRemove && (
              <button
                type="button"
                onClick={onRemove}
                aria-label={t("fileQueueItem.removeLabel")}
                title={t("fileQueueItem.removeTitle")}
                className="opacity-0 group-hover:opacity-100 p-1 rounded flex-shrink-0 focus-ring transition-opacity transition-colors duration-200 motion-reduce:transition-none hover:bg-destructive/10"
              >
                <Trash2 className="w-3.5 h-3.5 text-muted-foreground transition-colors duration-200 motion-reduce:transition-none hover:text-destructive" />
              </button>
            )}
          </div>
        )}
      </div>

      {file.status === 'error' && file.error && (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-2 py-1 rounded">
          {file.error}
        </p>
      )}
    </div>
  )
}
