'use client'

import { CornerUpLeft, Download, Maximize2, Minimize2, X } from '@/components/icons'

import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { Skeleton } from '@/components/ui/skeleton'
import type { Document } from '@/types/backend'

type DocumentViewerHeaderProps = {
  doc: Readonly<Pick<Document, 'filename' | 'chunk_count'>> | null
  isLoading: boolean
  isExpanded: boolean
  canDownload: boolean
  downloadLoading: boolean
  onDownload: () => Promise<void>
  onJumpToSource?: (() => void) | null
  onToggleExpanded: () => void
  onClose: () => void
}

export function DocumentViewerHeader({
  doc,
  isLoading,
  isExpanded,
  canDownload,
  downloadLoading,
  onDownload,
  onJumpToSource,
  onToggleExpanded,
  onClose,
}: Readonly<DocumentViewerHeaderProps>) {
  const filenameLabel = doc === null ? '文档信息' : doc.filename
  return (
    <div className="flex items-center justify-between border-b border-sidebar-border/70 bg-sidebar px-4 pb-3 pt-3 supports-[padding:env(safe-area-inset-top)]:pt-[calc(env(safe-area-inset-top)+0.75rem)]">
      <div className="flex items-center gap-3 overflow-hidden">
        <div className="rounded-xl p-2">
          <FileTypeIcon filename={doc?.filename} className="size-5" />
        </div>
        <div className="flex min-w-0 flex-col">
          <h2 className="max-w-[200px] truncate text-sm font-semibold leading-snug" title={doc?.filename}>
            {doc === null && isLoading ? (
              <Skeleton asChild className="block h-4 w-32">
                <span />
              </Skeleton>
            ) : (
              filenameLabel
            )}
          </h2>
          <span className="min-h-4 text-xs text-muted-foreground">
            {doc === null ? null : doc.chunk_count + ' 个切片'}
          </span>
        </div>
      </div>

      <div role="group" aria-label="文档操作" className="flex shrink-0 items-center gap-1">
        {onJumpToSource ? (
          <Button variant="ghost" size="sm" className="gap-2 rounded-full px-3 text-xs" onClick={onJumpToSource}>
            <CornerUpLeft className="size-4" />
            回到对话引用
          </Button>
        ) : null}
        <LoadingButton
          type="button"
          variant="ghost"
          size="icon"
          onClick={onDownload}
          disabled={!canDownload}
          loading={downloadLoading}
          title={downloadLoading ? '正在准备原文件' : '下载原文件'}
          aria-label="下载原文件"
        >
          <Download className="size-4" />
        </LoadingButton>
        <Button
          variant="ghost"
          size="icon"
          onClick={onToggleExpanded}
          title={isExpanded ? '收起' : '展开'}
          aria-label={isExpanded ? '收起' : '展开'}
        >
          {isExpanded ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
        </Button>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="关闭">
          <X className="size-4" />
        </Button>
      </div>
    </div>
  )
}
