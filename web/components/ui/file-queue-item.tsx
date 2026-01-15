'use client'

import { cn, formatFileSize } from '@/lib/utils'
import {
  FileText,
  FileSpreadsheet,
  FileType,
  File,
  Loader2,
  CheckCircle,
  XCircle,
  Trash2,
  RotateCcw,
  Clock,
} from 'lucide-react'

// 文件类型配置
const FILE_TYPE_CONFIG: Record<
  string,
  { icon: typeof FileText; color: string; bg: string }
> = {
  pdf: { icon: FileText, color: 'text-red-500', bg: 'bg-red-50' },
  xlsx: { icon: FileSpreadsheet, color: 'text-green-600', bg: 'bg-green-50' },
  xls: { icon: FileSpreadsheet, color: 'text-green-600', bg: 'bg-green-50' },
  docx: { icon: FileType, color: 'text-blue-600', bg: 'bg-blue-50' },
  doc: { icon: FileType, color: 'text-blue-600', bg: 'bg-blue-50' },
  txt: { icon: File, color: 'text-gray-600', bg: 'bg-gray-50' },
  md: { icon: FileText, color: 'text-purple-600', bg: 'bg-purple-50' },
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
  onClick?: () => void
  onRemove?: () => void
  onRetry?: () => void
}

export function FileQueueItem({
  file,
  isActive = false,
  onClick,
  onRemove,
  onRetry,
}: FileQueueItemProps) {
  const ext = file.name.split('.').pop()?.toLowerCase() || 'txt'
  const config = FILE_TYPE_CONFIG[ext] || FILE_TYPE_CONFIG.txt
  const Icon = config.icon

  const getStatusContent = () => {
    switch (file.status) {
      case 'pending':
        return (
          <div className="flex items-center gap-1.5 text-xs text-gray-500">
            <Clock className="w-3 h-3" />
            <span>等待解析</span>
          </div>
        )
      case 'parsing':
        return (
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5 text-xs text-blue-600">
              <Loader2 className="w-3 h-3 animate-spin" />
              <span>解析中 {file.progress ? `${file.progress}%` : ''}</span>
            </div>
            {file.progress !== undefined && (
              <div className="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 rounded-full transition-all duration-300"
                  style={{ width: `${file.progress}%` }}
                />
              </div>
            )}
          </div>
        )
      case 'parsed':
        return (
          <div className="flex items-center gap-2 text-xs">
            <span className="flex items-center gap-1 text-green-600">
              <CheckCircle className="w-3 h-3" />
              已完成
            </span>
            {file.parser && (
              <span className="text-gray-400">· {file.parser}</span>
            )}
            {file.chunkStrategyLabel && (
              <span className="text-gray-400">· {file.chunkStrategyLabel}</span>
            )}
            {file.duration && (
              <span className="text-gray-400">· {file.duration}s</span>
            )}
          </div>
        )
      case 'error':
        return (
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1 text-xs text-red-600">
              <XCircle className="w-3 h-3" />
              解析失败
            </span>
            {onRetry && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onRetry()
                }}
                className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700"
              >
                <RotateCcw className="w-3 h-3" />
                重试
              </button>
            )}
          </div>
        )
    }
  }

  return (
    <div
      className={cn(
        'group p-3 rounded-xl border transition-all cursor-pointer',
        isActive
          ? 'bg-sky-50 border-sky-200 shadow-sm'
          : 'bg-white border-gray-200 hover:border-sky-200 hover:bg-gray-50'
      )}
      onClick={onClick}
    >
      <div className="flex items-start gap-3">
        {/* 文件图标 */}
        <div className={cn('p-2.5 rounded-lg flex-shrink-0', config.bg)}>
          <Icon className={cn('w-5 h-5', config.color)} />
        </div>

        {/* 文件信息 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm font-medium text-gray-900 truncate">
              {file.name}
            </p>
            {onRemove && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onRemove()
                }}
                className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-50 rounded transition-all flex-shrink-0"
              >
                <Trash2 className="w-3.5 h-3.5 text-gray-400 hover:text-red-500" />
              </button>
            )}
          </div>

          {(file.folderPathLabel || file.sourcePath) && (
            <p
              className="mt-0.5 text-xs text-gray-400 truncate"
              title={[file.folderPathLabel, file.sourcePath].filter(Boolean).join(' · ')}
            >
              {file.folderPathLabel ? `目录：${file.folderPathLabel}` : ''}
              {file.sourcePath ? ` · ZIP：${file.sourcePath}` : ''}
            </p>
          )}

          <div className="flex items-center gap-2 mt-0.5 text-xs text-gray-400">
            <span>{formatFileSize(file.size)}</span>
            {file.pageCount && (
              <>
                <span>·</span>
                <span>{file.pageCount} 页</span>
              </>
            )}
          </div>

          <div className="mt-2">{getStatusContent()}</div>
        </div>
      </div>

      {/* 错误信息 */}
      {file.status === 'error' && file.error && (
        <p className="mt-2 text-xs text-red-500 bg-red-50 px-2 py-1 rounded">
          {file.error}
        </p>
      )}
    </div>
  )
}
