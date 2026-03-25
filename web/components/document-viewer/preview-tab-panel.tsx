"use client"

import { FileText, Loader2 } from "lucide-react"

import type { Document } from "@/types"
import { Button } from "@/components/ui/button"

type PreviewTabPanelProps = {
  isLoading: boolean
  doc: Document | null
  canInlinePreview: boolean
  fileUrl: string | null
  rawFileUrl: string | null
  downloadUrl: string | null
  onViewChunks: () => void
}

export function PreviewTabPanel({
  isLoading,
  doc,
  canInlinePreview,
  fileUrl,
  rawFileUrl,
  downloadUrl,
  onViewChunks,
}: Readonly<PreviewTabPanelProps>) {
  if (isLoading && !doc) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none" />
      </div>
    )
  }

  if (canInlinePreview && fileUrl) {
    return <iframe src={`${fileUrl}#toolbar=0`} className="h-full w-full border-none" title="Document Preview" />
  }

  if (canInlinePreview && rawFileUrl) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none" />
      </div>
    )
  }

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-md rounded-xl border border-border bg-background p-6 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-primary/10 p-2">
            <FileText className="h-5 w-5 text-primary" />
          </div>
          <div className="flex-1">
            <h4 className="text-sm font-semibold">暂不支持内嵌预览</h4>
            <p className="mt-1 text-xs text-muted-foreground">
              当前文件类型为 <span className="font-mono">{doc?.file_type || "-"}</span>。你可以下载原文件，或切换到「智能切片」查看内容。
            </p>
            <div className="mt-4 flex items-center gap-2">
              <Button size="sm" variant="outline" asChild>
                <a href={downloadUrl || "#"} target="_blank" rel="noopener noreferrer">
                  下载原文件
                </a>
              </Button>
              <Button size="sm" onClick={onViewChunks}>
                查看切片
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
