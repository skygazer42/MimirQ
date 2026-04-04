"use client"

import { FileText, Loader2 } from "lucide-react"

import type { ChunkPreviewItem, Citation, DocumentParsedContentResponse } from "@/types"
import { Button } from "@/components/ui/button"
import { OriginalPreviewMonaco } from "@/components/chunk-preview/components/workbench/preview/original-preview-monaco"
import { cn } from "@/lib/utils"

type TextTabPanelProps = {
  textMode: "cleaned" | "original"
  highlightChunkId: string | null
  loadAllChunks: boolean
  chunksLoaded: boolean
  chunksLoading: boolean
  retrieveQuery: string
  retrieveLoading: boolean
  retrieveError: string | null
  retrieveCitations: Citation[]
  parsedContent: DocumentParsedContentResponse | null
  parsedContentLoading: boolean
  parsedContentError: string | null
  textValue: string
  textChunkItems: ChunkPreviewItem[]
  textActiveChunkIndex: number | null
  initialScrollTop: number
  highlightRange: { start: number; end: number } | null
  onTextModeChange: (mode: "cleaned" | "original") => void
  onTextScrollTopChange: (scrollTop: number) => void
  onClearHighlight: () => void
  onLoadAllChunks: () => void
  onRetrieveQueryChange: (value: string) => void
  onRunRetrieve: () => void
  onClearRetrieve: () => void
  onSelectRetrieveChunk: (chunkId: string) => void
  onSelectChunkIndex: (chunkIndex: number) => void
  onGoToChunks: () => void
  onGoToPreview: () => void
}

export function TextTabPanel({
  textMode,
  highlightChunkId,
  loadAllChunks,
  chunksLoaded,
  chunksLoading,
  retrieveQuery,
  retrieveLoading,
  retrieveError,
  retrieveCitations,
  parsedContent,
  parsedContentLoading,
  parsedContentError,
  textValue,
  textChunkItems,
  textActiveChunkIndex,
  initialScrollTop,
  highlightRange,
  onTextModeChange,
  onTextScrollTopChange,
  onClearHighlight,
  onLoadAllChunks,
  onRetrieveQueryChange,
  onRunRetrieve,
  onClearRetrieve,
  onSelectRetrieveChunk,
  onSelectChunkIndex,
  onGoToChunks,
  onGoToPreview,
}: Readonly<TextTabPanelProps>) {
  return (
    <div className="flex h-full flex-col overflow-hidden bg-muted/20 dark:bg-muted/10">
      <div className="border-b border-border bg-background/60 p-4 backdrop-blur-sm">
        <div className="flex flex-col gap-2">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" size="sm" variant={textMode === "cleaned" ? "secondary" : "outline"} onClick={() => onTextModeChange("cleaned")}>
                清洗后
              </Button>
              <Button type="button" size="sm" variant={textMode === "original" ? "secondary" : "outline"} onClick={() => onTextModeChange("original")}>
                原始解析
              </Button>

              {highlightChunkId && !loadAllChunks && !chunksLoaded ? (
                <span className="text-[11px] text-muted-foreground">仅加载引用切片位置；如需展示全部切片位置，请点右侧「加载全部切片」。</span>
              ) : null}
            </div>

            <div className="flex items-center justify-end gap-2">
              {highlightChunkId ? (
                <Button type="button" size="sm" variant="outline" onClick={onClearHighlight}>
                  清除定位
                </Button>
              ) : null}

              {chunksLoaded ? null : (
                <Button type="button" size="sm" onClick={onLoadAllChunks} disabled={chunksLoading}>
                  加载全部切片
                </Button>
              )}
            </div>
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <input
              value={retrieveQuery}
              onChange={(event) => onRetrieveQueryChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return
                event.preventDefault()
                onRunRetrieve()
              }}
              placeholder="检索测试：输入问题，查看真实检索命中的切片…"
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
            <div className="flex items-center justify-end gap-2">
              <Button type="button" size="sm" variant="outline" disabled={!retrieveQuery.trim() || retrieveLoading} onClick={onRunRetrieve}>
                {retrieveLoading ? (
                  <span className="inline-flex items-center gap-2">
                    <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                    检索中…
                  </span>
                ) : (
                  "检索"
                )}
              </Button>
              {retrieveCitations.length ? (
                <Button type="button" size="sm" variant="outline" onClick={onClearRetrieve}>
                  清空
                </Button>
              ) : null}
            </div>
          </div>

          {retrieveError ? (
            <div className="rounded-lg border border-destructive/25 bg-destructive/10 px-2 py-1 text-[11px] text-destructive">{retrieveError}</div>
          ) : null}

          {retrieveCitations.length ? (
            <div className="max-h-[220px] overflow-auto rounded-xl border border-border/60 bg-background/60 p-3">
              <div className="mb-2 text-xs font-semibold text-foreground">检索命中</div>
              <div className="space-y-2">
                {retrieveCitations.slice(0, 6).map((citation) => {
                  const hasChunk = Boolean(citation.chunk_id)
                  return (
                    <button
                      key={`${String(citation.document_id || "")}:${String(citation.chunk_id || "")}:${String(citation.page_number ?? "")}`}
                      type="button"
                      className={cn(
                        "w-full rounded-lg border border-border bg-background px-3 py-2 text-left",
                        "transition-colors hover:border-primary/30 hover:bg-muted/30",
                      )}
                      disabled={!hasChunk}
                      onClick={() => {
                        if (!citation.chunk_id) return
                        onSelectRetrieveChunk(citation.chunk_id)
                      }}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-[11px] text-muted-foreground">
                          score <span className="font-mono">{Number(citation.relevance_score || 0).toFixed(4)}</span>
                          {typeof citation.page_number === "number" ? <span className="ml-2">P.{citation.page_number}</span> : null}
                        </div>
                        <div className="text-[11px] text-muted-foreground">{hasChunk ? "点击定位" : "无 chunk_id"}</div>
                      </div>
                      <div className="mt-1 line-clamp-3 whitespace-pre-wrap font-mono text-xs leading-relaxed text-foreground/90">
                        {citation.chunk_content || ""}
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          ) : null}

          {textMode === "original" ? (
            <div className="text-[11px] text-muted-foreground">提示：切片的 start/end 偏移通常基于「清洗后」文本；在「原始解析」视图中高亮定位可能不准确。</div>
          ) : null}

          {parsedContent?.markdown_truncated || parsedContent?.original_markdown_truncated ? (
            <div className="text-[11px] text-muted-foreground">
              文本已截断显示（max_chars={parsedContent?.max_chars ?? 0}）。如需完整内容，请提高 persist_parsed_content_max_chars 或缩小文件。
            </div>
          ) : null}

          {parsedContentError ? (
            <div className="rounded-lg border border-destructive/25 bg-destructive/10 px-2 py-1 text-[11px] text-destructive">{parsedContentError}</div>
          ) : null}
        </div>
      </div>

      <div className="flex-1 overflow-hidden p-4">
        {parsedContentLoading && !parsedContent ? (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            <Loader2 className="size-8 animate-spin motion-reduce:animate-none" />
          </div>
        ) : parsedContent?.available && textValue ? (
          <OriginalPreviewMonaco
            text={textValue}
            chunks={textMode === "cleaned" ? textChunkItems : []}
            activeChunkIndex={textMode === "cleaned" ? textActiveChunkIndex : null}
            activeRange={textMode === "cleaned" ? highlightRange ?? null : null}
            initialScrollTop={initialScrollTop}
            onScrollTopChange={onTextScrollTopChange}
            onSelectChunkIndex={onSelectChunkIndex}
          />
        ) : (
          <div className="flex h-full items-center justify-center p-6">
            <div className="w-full max-w-md rounded-xl border border-border bg-background p-6 shadow-sm">
              <div className="flex items-start gap-3">
                <div className="rounded-lg bg-primary/10 p-2">
                  <FileText className="size-5 text-primary" />
                </div>
                <div className="flex-1">
                  <h4 className="text-sm font-semibold">未持久化解析文本</h4>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    当前文档未开启 <span className="font-mono">persist_parsed_content</span>，因此无法在此处高亮定位切片位置。你可以在上传/流水线配置中开启该选项后重新入库，或继续使用「智能切片」查看内容。
                  </p>
                  <div className="mt-4 flex items-center gap-2">
                    <Button size="sm" variant="outline" onClick={onGoToChunks}>
                      查看切片
                    </Button>
                    <Button size="sm" variant="outline" onClick={onGoToPreview}>
                      返回原文
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
