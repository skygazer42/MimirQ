"use client"

import { FileText, Loader2 } from "lucide-react"

import type { DocumentPreviewAnchor } from "@/lib/document-preview-anchor"
import { buildPdfPreviewSrc } from "@/lib/document-preview-anchor"
import type { Document } from "@/types"
import { Button } from "@/components/ui/button"

type PreviewTabPanelProps = {
  isLoading: boolean
  doc: Document | null
  canInlinePreview: boolean
  fileUrl: string | null
  rawFileUrl: string | null
  downloadUrl: string | null
  previewAnchor: DocumentPreviewAnchor | null
  highlightChunkId: string | null
  highlightRange: { start: number; end: number } | null
  onViewText: () => void
  onViewChunks: () => void
}

export function PreviewTabPanel({
  isLoading,
  doc,
  canInlinePreview,
  fileUrl,
  rawFileUrl,
  downloadUrl,
  previewAnchor,
  highlightChunkId,
  highlightRange,
  onViewText,
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
    const hasAnchorContext = Boolean(previewAnchor || highlightChunkId || highlightRange)
    const title = previewAnchor?.pageNumber ? "PDF 已跳转到引用页" : "已保留引用定位"
    const description = previewAnchor?.pageNumber
      ? `当前定位到 P.${previewAnchor.pageNumber}${previewAnchor.searchText ? `，并尝试搜索“${previewAnchor.searchText}”` : ""}。`
      : "当前引用定位已保留，可切回文本定位查看高亮，或切到智能切片查看命中块。"

    return (
      <div className="relative h-full w-full">
        {hasAnchorContext ? (
          <div className="absolute inset-x-4 top-4 z-10 flex justify-end">
            <div className="max-w-md rounded-xl border border-border/70 bg-background/95 p-3 shadow-lg backdrop-blur">
              <div className="text-xs font-semibold text-foreground">{title}</div>
              <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{description}</p>
              <div className="mt-3 flex flex-wrap justify-end gap-2">
                {highlightRange ? (
                  <Button type="button" size="sm" variant="outline" onClick={onViewText}>
                    查看文本高亮
                  </Button>
                ) : null}
                {highlightChunkId ? (
                  <Button type="button" size="sm" onClick={onViewChunks}>
                    查看切片
                  </Button>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}
        <iframe
          src={buildPdfPreviewSrc(fileUrl, previewAnchor)}
          className="h-full w-full border-none"
          title="Document Preview"
        />
      </div>
    )
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
