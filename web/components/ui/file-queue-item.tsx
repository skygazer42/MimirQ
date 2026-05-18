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
import { Progress } from '@/components/ui/progress'

// 文件类型配置 — 使用 token 色
const FILE_TYPE_CONFIG: Record<
  string,
  { icon: typeof FileText; color: string; bg: string }
> = {
  pdf: { icon: FileText, color: 'text-destructive', bg: 'bg-destructive/10' },
  pptx: { icon: Presentation, color: 'text-warning', bg: 'bg-warning/10' },
  ppt: { icon: Presentation, color: 'text-warning', bg: 'bg-warning/10' },
  xlsx: { icon: FileSpreadsheet, color: 'text-success', bg: 'bg-success/10' },
  xls: { icon: FileSpreadsheet, color: 'text-success', bg: 'bg-success/10' },
  docx: { icon: FileType, color: 'text-info', bg: 'bg-info/10' },
  doc: { icon: FileType, color: 'text-info', bg: 'bg-info/10' },
  txt: { icon: File, color: 'text-muted-foreground', bg: 'bg-muted/60' },
  md: { icon: FileText, color: 'text-accent', bg: 'bg-accent/10' },
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
  governanceStatus?: 'draft' | 'ready' | 'submitted'
}

interface FileQueueItemProps {
  file: FileQueueItemData
  isActive?: boolean
  isSelected?: boolean
  isSelectable?: boolean
  draggable?: boolean
  onDragStart?: (e: React.DragEvent<HTMLElement>) => void
  onClick?: () => void
  onToggleSelected?: () => void
  onRemove?: () => void
  onRetry?: () => void
}

export function FileQueueItem({
  file,
  isActive = false,
  isSelected = false,
  isSelectable = false,
  draggable = false,
  onDragStart,
  onClick,
  onToggleSelected,
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
  const parsedSummary = [file.parser, file.chunkStrategyLabel].filter(Boolean).join(' · ')
  const governanceStatusLabel =
    file.governanceStatus === 'ready' ? '待提交' : file.governanceStatus === 'submitted' ? '已提交' : ''

  const getStatusContent = () => {
    switch (file.status) {
      case 'pending':
        return (
          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Clock className="size-3" />
            <span>{t("fileQueueItem.pending")}</span>
          </div>
        )
      case 'parsing':
        return (
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5 text-[11px] text-info">
              <Loader2 className="size-3 animate-spin motion-reduce:animate-none" />
              <span>{t("fileQueueItem.parsing")} {file.progress == null ? '' : `${progressPct}%`}</span>
            </div>
            {file.progress !== undefined && (
              <Progress value={progressPct} className="h-1.5" />
            )}
          </div>
        )
      case 'parsed':
        return (
          <div className="flex min-w-0 items-center gap-2 text-[11px]">
            <span className="inline-flex shrink-0 items-center gap-1 text-success">
              <CheckCircle className="size-3.5" />
              {t("fileQueueItem.parsed")}
            </span>
            {parsedSummary ? (
              <span className="min-w-0 truncate text-muted-foreground">
                {parsedSummary}
              </span>
            ) : null}
            {governanceStatusLabel ? (
              <span
                className={cn(
                  'shrink-0 rounded-full border px-1.5 py-0.5 font-medium',
                  file.governanceStatus === 'ready'
                    ? 'border-warning/25 bg-warning/[0.10] text-warning'
                    : 'border-success/25 bg-success/[0.08] text-success'
                )}
              >
                {governanceStatusLabel}
              </span>
            ) : null}
            {typeof file.duration === 'number' && Number.isFinite(file.duration) ? (
              <span className="ml-auto shrink-0 font-mono tabular-nums text-[11px] text-muted-foreground">
                {file.duration}s
              </span>
            ) : null}
          </div>
        )
      case 'error':
        return (
          <div className="flex items-center gap-1.5 text-[11px] text-destructive">
            <XCircle className="size-3.5" />
            <span>{t("fileQueueItem.error")}</span>
            {onRetry ? (
              <span className="ml-auto shrink-0 font-medium text-destructive/80">
                {t("fileQueueItem.retry")}
              </span>
            ) : null}
          </div>
        )
    }
  }

  const fileContent = (
    <>
      <div className={cn('flex size-8 shrink-0 items-center justify-center rounded-md', config.bg)}>
        <Icon className={cn('size-4', config.color)} />
      </div>

      <div className="flex-1 min-w-0">
        <p className="truncate text-[13px] font-medium text-foreground">
          {file.name}
        </p>

        {(file.folderPathLabel || file.sourcePath) && (
          <p
            className="mt-0.5 truncate text-[11px] text-muted-foreground"
            title={[file.folderPathLabel, file.sourcePath].filter(Boolean).join(' · ')}
          >
            {file.folderPathLabel ? `${t("fileQueueItem.folderLabel")}${file.folderPathLabel}` : ''}
            {file.sourcePath ? ` · ${t("fileQueueItem.sourcePathLabel")}${file.sourcePath}` : ''}
          </p>
        )}

        <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <span>{formatFileSize(file.size)}</span>
          {file.pageCount && (
            <>
              <span>·</span>
              <span>{t("fileQueueItem.pages", { count: String(file.pageCount) })}</span>
            </>
          )}
        </div>

        <div className="mt-1.5">{getStatusContent()}</div>
      </div>
    </>
  )

  return (
    <div
      className={cn(
        'group cursor-pointer rounded-md border border-transparent px-2.5 py-2 transition-colors duration-150 motion-reduce:transition-none',
        isActive
          ? 'bg-primary/[0.055] shadow-none'
          : 'bg-background/60 hover:bg-muted/35'
      )}
    >
      <div className="flex items-start gap-2">
        {isSelectable ? (
          <button
            type="button"
            aria-pressed={isSelected}
            aria-label={isSelected ? '取消选择待提交文档' : '选择待提交文档'}
            className={cn(
              'mt-1 flex size-5 shrink-0 items-center justify-center rounded-full border transition-colors focus-ring',
              isSelected
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-border/70 bg-background text-transparent hover:border-primary/50 hover:text-primary/40'
            )}
            onClick={(event) => {
              event.stopPropagation()
              onToggleSelected?.()
            }}
          >
            <CheckCircle className="size-3.5" />
          </button>
        ) : null}

        {onClick ? (
          <button
            type="button"
            className="flex min-w-0 flex-1 items-start gap-2 rounded-md text-left focus-ring"
            onClick={onClick}
            draggable={draggable}
            onDragStart={onDragStart}
          >
            {fileContent}
          </button>
        ) : (
          <div className="flex min-w-0 flex-1 items-start gap-2">
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
                <RotateCcw className="size-3" />
                {t("fileQueueItem.retry")}
              </button>
            )}
            {onRemove && (
              <button
                type="button"
                onClick={onRemove}
                aria-label={t("fileQueueItem.removeLabel")}
                title={t("fileQueueItem.removeTitle")}
                className="rounded p-1 opacity-0 transition-opacity transition-colors duration-200 focus-ring motion-reduce:transition-none group-hover:opacity-100 hover:bg-destructive/10"
              >
                <Trash2 className="size-3.5 text-muted-foreground transition-colors duration-200 motion-reduce:transition-none hover:text-destructive" />
              </button>
            )}
          </div>
        )}
      </div>

      {file.status === 'error' && file.error && (
        <p className="mt-2 rounded bg-destructive/10 px-2 py-1 text-[11px] text-destructive">
          {file.error}
        </p>
      )}
    </div>
  )
}
