"use client"

import { CornerUpLeft, Download, FileText, Maximize2, Minimize2, X } from "lucide-react"

import { Button } from "@/components/ui/button"

type DocumentViewerHeaderProps = {
  filename?: string | null
  chunkCount: number
  isExpanded: boolean
  downloadUrl: string | null
  onJumpToSource?: (() => void) | null
  onToggleExpanded: () => void
  onClose: () => void
}

export function DocumentViewerHeader({
  filename,
  chunkCount,
  isExpanded,
  downloadUrl,
  onJumpToSource,
  onToggleExpanded,
  onClose,
}: Readonly<DocumentViewerHeaderProps>) {
  return (
    <div className="flex items-center justify-between border-b border-sidebar-border/70 bg-sidebar px-4 pb-3 pt-3 supports-[padding:env(safe-area-inset-top)]:pt-[calc(env(safe-area-inset-top)+0.75rem)]">
      <div className="flex items-center gap-3 overflow-hidden">
        <div className="rounded-xl p-2">
          <FileText className="size-5 text-muted-foreground" />
        </div>
        <div className="flex min-w-0 flex-col">
          <h3 className="max-w-[200px] truncate text-sm font-semibold leading-snug" title={filename ?? undefined}>
            {filename || "加载中..."}
          </h3>
          <span className="text-xs text-muted-foreground">{chunkCount} 个切片</span>
        </div>
      </div>

      <div className="flex items-center gap-1">
        {onJumpToSource ? (
          <Button variant="ghost" size="sm" className="gap-2 rounded-full px-3 text-xs" onClick={onJumpToSource}>
            <CornerUpLeft className="size-4" />
            回到对话引用
          </Button>
        ) : null}
        <Button variant="ghost" size="icon" asChild title="下载原文件" aria-label="下载原文件">
          <a href={downloadUrl || "#"} target="_blank" rel="noopener noreferrer">
            <Download className="size-4" />
          </a>
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={onToggleExpanded}
          title={isExpanded ? "收起" : "展开"}
          aria-label={isExpanded ? "收起" : "展开"}
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
