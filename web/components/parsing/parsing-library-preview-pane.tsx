'use client'

import { Copy, FolderOpen, MoreVertical, Paperclip, Play, X } from 'lucide-react'
import { toast } from 'sonner'

import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { getFileIcon } from '@/components/document-library/folder-tree'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { ParsingRightPanel } from '@/components/parsing/parsing-right-panel'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import type { ParsedFileData } from '@/store/use-parsed-files-store'

type StatusBadge = {
  label: string
  cls: string
}

type ParsingLibraryPreviewPaneProps = {
  file: ParsedFileData
  activeMarkdown: string
  folderName: string
  folderPathLabel: string
  sourceStatus: 'unknown' | 'available' | 'missing'
  defaultParserBackend: string
  statusBadge?: StatusBadge | null
  onClose: () => void
  onUpdateParser: (backend: string) => void
  onRestoreSource: (autoParse: boolean) => void
  onRequestRebind: (autoParse: boolean) => void
}

export function ParsingLibraryPreviewPane({
  file,
  activeMarkdown,
  folderName,
  folderPathLabel,
  sourceStatus,
  defaultParserBackend,
  statusBadge,
  onClose,
  onUpdateParser,
  onRestoreSource,
  onRequestRebind,
}: Readonly<ParsingLibraryPreviewPaneProps>) {
  const parserValue = resolveParserBackendForFilename(
    file.filename,
    file.parserBackend || defaultParserBackend
  ).backend
  const pendingParseAction = (() => {
    if (!file.status || file.status === 'parsed') return null
    if (sourceStatus === 'available') {
      return {
        label: '继续解析',
        title: '恢复并开始解析',
        onClick: () => onRestoreSource(true),
      }
    }
    return {
      label: '上传并解析',
      title: '重新上传并开始解析',
      onClick: () => onRequestRebind(true),
    }
  })()

  return (
    <div className="flex flex-1 flex-col min-h-0">
      <div className="border-b border-border/60 bg-card/80 px-6 py-2 dark:bg-background/60">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex max-w-[560px] min-w-0 items-center gap-2 rounded-xl border border-border/60 bg-background/70 px-2.5 py-1 text-sm font-semibold text-foreground dark:bg-background/20">
                {getFileIcon(file.filename, 'w-7 h-7 rounded-lg')}
                <span className="min-w-0 truncate">{file.filename}</span>
              </span>
              <span
                className="inline-flex items-center gap-1 rounded-full bg-muted/60 px-2 py-0.5 text-[10px] text-muted-foreground dark:bg-muted/60 dark:text-muted-foreground"
                title={folderPathLabel}
              >
                <FolderOpen className="h-3 w-3" />
                {folderName}
              </span>
              {statusBadge ? (
                <span
                  className={cn('rounded-full border px-2 py-0.5 text-[10px] font-medium', statusBadge.cls)}
                  title={file.status}
                >
                  {statusBadge.label}
                </span>
              ) : null}
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2">
            {file.status && file.status !== 'parsed' ? (
              <ParserDropdown
                value={parserValue}
                filename={file.filename}
                onChange={onUpdateParser}
                className="w-full sm:w-64"
                compact
              />
            ) : (
              <span className="text-xs text-muted-foreground">
                解析方式：<span className="font-medium text-foreground/80 dark:text-muted-foreground">{file.parser || getParserLabel(parserValue)}</span>
              </span>
            )}

            {sourceStatus === 'available' ? (
              <Button
                variant="outline"
                size="sm"
                className="h-8 gap-1.5 rounded-full px-3 text-[11px]"
                onClick={() => onRestoreSource(false)}
                title="从服务器下载源文件到队列（用于 PDF 预览或继续解析）"
              >
                <Paperclip className="h-3.5 w-3.5" />
                恢复源文件
              </Button>
            ) : (
              <Button
                variant="outline"
                size="sm"
                className="h-8 gap-1.5 rounded-full px-3 text-[11px]"
                onClick={() => onRequestRebind(false)}
                title="重新上传源文件以替换服务器上的源文件"
              >
                <Paperclip className="h-3.5 w-3.5" />
                重新上传
              </Button>
            )}

            {pendingParseAction ? (
              <Button
                size="sm"
                className="h-8 gap-1.5 rounded-full bg-sky-600 px-3 text-[11px] hover:bg-sky-700"
                onClick={pendingParseAction.onClick}
                title={pendingParseAction.title}
              >
                <Play className="h-3.5 w-3.5" />
                {pendingParseAction.label}
              </Button>
            ) : null}

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="icon"
                  className="h-8 w-8 rounded-full"
                  aria-label="更多操作"
                  title="更多"
                >
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-44">
                <DropdownMenuItem
                  className="cursor-pointer gap-2"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(file.filename)
                      toast.success('已复制文件名')
                    } catch {
                      toast.error('复制失败')
                    }
                  }}
                >
                  <Copy className="h-4 w-4 text-muted-foreground" />
                  复制文件名
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem className="cursor-pointer gap-2" onClick={onClose}>
                  <X className="h-4 w-4 text-muted-foreground" />
                  关闭
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-hidden min-h-0">
        {activeMarkdown ? (
          <ParsingRightPanel className="h-full no-scrollbar px-6 py-6">
            <MarkdownRenderer markdown={activeMarkdown} />
          </ParsingRightPanel>
        ) : (
          <div className="flex h-full items-center justify-center">
            <div className="max-w-md text-center">
              <div className="mx-auto mb-3 flex size-16 items-center justify-center rounded-2xl border border-border/60 bg-card shadow-soft">
                <FolderOpen className="h-8 w-8 text-muted-foreground dark:text-muted-foreground" />
              </div>
              <p className="text-sm font-medium text-muted-foreground dark:text-muted-foreground">暂无可展示的解析内容</p>
              <p className="mt-1 text-xs text-muted-foreground dark:text-muted-foreground">若该文件还未解析，或内容未缓存，请重新选择文件并解析。</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
