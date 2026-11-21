'use client'

import { useId, useMemo, useState } from 'react'
import { FileText } from '@/components/icons'
import { Skeleton } from '@/components/ui/skeleton'

import type { DocumentPreviewAnchor } from '@/lib/document-preview-anchor'
import { buildDocumentPreviewBboxOverlay, DOCUMENT_PREVIEW_BBOX_ID } from '@/lib/document-preview-anchor'
import { cn } from '@/lib/utils'
import type { Document } from '@/types/backend'
import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { PdfViewer } from '@/components/parsing/pdf-viewer'

type PreviewTabPanelProps = {
  isLoading: boolean
  doc: Document | null
  canInlinePreview: boolean
  fileUrl: string | null
  downloadLoading: boolean
  onDownload: () => Promise<void>
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
  downloadLoading,
  onDownload,
  previewAnchor,
  highlightChunkId,
  highlightRange,
  onViewText,
  onViewChunks,
}: Readonly<PreviewTabPanelProps>) {
  const [anchorActionsCollapsed, setAnchorActionsCollapsed] = useState(false)
  const anchorActionsId = useId()
  const bboxOverlay = useMemo(() => buildDocumentPreviewBboxOverlay(previewAnchor), [previewAnchor])
  const bboxPageIndex = bboxOverlay?.blockIdToPageIndex.get(DOCUMENT_PREVIEW_BBOX_ID)
  const anchorPageNumber = previewAnchor?.pageNumber
  const fallbackPageNumber =
    typeof anchorPageNumber === 'number' && Number.isInteger(anchorPageNumber) && anchorPageNumber > 0
      ? anchorPageNumber
      : null
  const previewPageNumber = bboxPageIndex === undefined ? fallbackPageNumber : bboxPageIndex + 1
  const previewPageIndex = bboxOverlay === null && fallbackPageNumber !== null ? fallbackPageNumber - 1 : null

  if (isLoading && doc === null) {
    return (
      <div role="status" aria-label="正在读取文档信息" className="h-full overflow-hidden p-6">
        <Skeleton className="h-64 max-h-full w-full" />
      </div>
    )
  }

  if (doc === null) return null

  if (canInlinePreview && fileUrl !== null) {
    const hasAnchorContext = previewAnchor !== null || highlightChunkId !== null || highlightRange !== null
    const toggleLabel = anchorActionsCollapsed ? '展开引用定位' : '收起引用定位'
    const searchDescription = previewAnchor?.searchText ? `引用文字：“${previewAnchor.searchText}”。` : null
    const description =
      previewPageNumber !== null
        ? `引用位于第 ${previewPageNumber} 页。`
        : '切换到「文本定位」看高亮，或在「切片」中查看引用片段。'

    return (
      <div className="relative h-full w-full">
        {hasAnchorContext ? (
          <div className="pointer-events-none absolute inset-x-4 top-4 z-10 flex justify-end">
            <div
              className={cn(
                'pointer-events-auto relative max-w-md',
                !anchorActionsCollapsed &&
                  'rounded-xl border border-border/70 bg-background/95 p-3 shadow-lg backdrop-blur',
              )}
            >
              <button
                type="button"
                aria-label={toggleLabel}
                aria-expanded={!anchorActionsCollapsed}
                aria-controls={anchorActionsId}
                onClick={() => setAnchorActionsCollapsed((collapsed) => !collapsed)}
                className={cn(
                  'flex items-center justify-center rounded-full border border-border/70 transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
                  anchorActionsCollapsed
                    ? 'size-10 bg-background/95 text-xs font-semibold text-foreground shadow-lg backdrop-blur'
                    : 'absolute right-3 top-3 size-7 bg-background/80 text-sm leading-none text-muted-foreground hover:text-foreground',
                )}
                title={toggleLabel}
              >
                {anchorActionsCollapsed ? '引' : '-'}
              </button>
              <div id={anchorActionsId} hidden={anchorActionsCollapsed}>
                <div className="pr-10">
                  <div className="text-xs font-semibold text-foreground">引用定位</div>
                  <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                    {description}
                    {searchDescription}
                  </p>
                </div>
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
          </div>
        ) : null}
        <div
          data-pdfjs-document-preview="true"
          data-citation-bbox-preview={bboxOverlay ? 'true' : undefined}
          className="h-full w-full bg-muted/20"
        >
          <PdfViewer
            fileUrl={fileUrl}
            boxesByPage={bboxOverlay?.boxesByPage}
            blockIdToPageIndex={bboxOverlay?.blockIdToPageIndex}
            activeBlockIds={bboxOverlay?.activeBlockIds}
            scrollToPageIndex={previewPageIndex}
            showAllBoxes={false}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-md rounded-xl border border-border bg-background p-6 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-primary/10 p-2">
            <FileText className="size-5 text-primary" />
          </div>
          <div className="flex-1">
            <h4 className="text-sm font-semibold">暂不支持内嵌预览</h4>
            <p className="mt-1 text-xs text-muted-foreground">
              当前文件格式为 <span className="font-mono">{doc.file_type}</span>。
            </p>
            <div className="mt-4 flex items-center gap-2">
              <LoadingButton type="button" size="sm" variant="outline" loading={downloadLoading} onClick={onDownload}>
                下载原文件
              </LoadingButton>
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
