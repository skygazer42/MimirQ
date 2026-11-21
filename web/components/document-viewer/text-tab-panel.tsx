'use client'

import { FileText, Loader2 } from '@/components/icons'
import type { ReactNode } from 'react'

import type { DocumentParsedContentResponse } from '@/types/backend'
import type { ChunkPreviewItem, Citation } from '@/types/processing'
import { Button } from '@/components/ui/button'
import { OriginalPreviewMonaco } from '@/components/chunk-preview/components/workbench/preview/original-preview-monaco'
import { cn } from '@/lib/utils'

type TextTabPanelProps = {
  textMode: 'cleaned' | 'original'
  highlightChunkId: string | null
  loadAllChunks: boolean
  chunksLoaded: boolean
  chunksLoading: boolean
  retrieveQuery: string
  retrieveLoading: boolean
  retrieveError: string | null
  retrieveFailedQuery: string | null
  retrieveCitations: Citation[]
  retrieveResultQuery: string | null
  parsedContent: DocumentParsedContentResponse | null
  parsedContentLoading: boolean
  parsedContentError: string | null
  onRetryParsedContent: () => void
  textValue: string
  textChunkItems: ChunkPreviewItem[]
  unpositionedChunkCount: number
  textActiveChunkIndex: number | null
  initialScrollTop: number
  highlightRange: { start: number; end: number } | null
  highlightParentRange: boolean
  onTextModeChange: (mode: 'cleaned' | 'original') => void
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

function getTextTabRetrieveButtonLabel(retrieveLoading: boolean): ReactNode {
  if (retrieveLoading) {
    return (
      <span className="inline-flex items-center gap-2">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
        检索中…
      </span>
    )
  }
  return '检索'
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
  retrieveFailedQuery,
  retrieveCitations,
  retrieveResultQuery,
  parsedContent,
  parsedContentLoading,
  parsedContentError,
  onRetryParsedContent,
  textValue,
  textChunkItems,
  unpositionedChunkCount,
  textActiveChunkIndex,
  initialScrollTop,
  highlightRange,
  highlightParentRange,
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
  const previewChunks = textMode === 'cleaned' ? textChunkItems : []
  const previewActiveChunkIndex = textMode === 'cleaned' ? textActiveChunkIndex : null
  const previewActiveRange = textMode === 'cleaned' ? highlightRange : null

  let retrieveResultsPanel: ReactNode = null
  if (retrieveResultQuery !== null) {
    retrieveResultsPanel = (
      <div className="max-h-[220px] overflow-auto rounded-xl border border-border/60 bg-background/60 p-3">
        <div className="mb-2 text-xs font-semibold text-foreground">检索结果</div>
        <p className="mb-2 break-words text-xs text-muted-foreground">查询：{retrieveResultQuery}</p>
        {retrieveCitations.length === 0 ? <p className="text-xs text-muted-foreground">未找到匹配的切片。</p> : null}
        <div className="space-y-2">
          {retrieveCitations.slice(0, 6).map((citation) => {
            const chunkId = citation.chunk_id
            const hasChunk = chunkId !== undefined && chunkId !== ''
            return (
              <button
                key={JSON.stringify([
                  citation.document_id,
                  chunkId,
                  citation.chunk_index,
                  citation.page_number,
                  citation.start_char,
                  citation.end_char,
                ])}
                type="button"
                className={cn(
                  'w-full rounded-lg border border-border bg-background px-3 py-2 text-left',
                  'transition-colors hover:border-primary/30 hover:bg-muted/30',
                )}
                disabled={!hasChunk}
                onClick={() => {
                  if (hasChunk) onSelectRetrieveChunk(chunkId)
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[11px] text-muted-foreground">
                    score <span className="font-mono">{citation.relevance_score.toFixed(4)}</span>
                    {typeof citation.page_number === 'number' ? (
                      <span className="ml-2">P.{citation.page_number}</span>
                    ) : null}
                  </div>
                  <div className="text-[11px] text-muted-foreground">{hasChunk ? '点击定位' : '无 chunk_id'}</div>
                </div>
                <div className="mt-1 line-clamp-3 whitespace-pre-wrap font-mono text-xs leading-relaxed text-foreground/90">
                  {citation.chunk_content}
                </div>
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  let textPanelContent: ReactNode = null
  if (parsedContentLoading && !parsedContent) {
    textPanelContent = (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="size-8 animate-spin motion-reduce:animate-none" />
      </div>
    )
  } else if (parsedContent?.available && textValue) {
    textPanelContent = (
      <OriginalPreviewMonaco
        text={textValue}
        chunks={previewChunks}
        activeChunkIndex={previewActiveChunkIndex}
        activeRange={previewActiveRange}
        highlightParentRange={highlightParentRange}
        initialScrollTop={initialScrollTop}
        onScrollTopChange={onTextScrollTopChange}
        onSelectChunkIndex={onSelectChunkIndex}
      />
    )
  } else if (parsedContent?.available) {
    textPanelContent = (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-muted-foreground">
        <FileText className="size-6" />
        <h4 className="text-sm font-semibold">正文为空</h4>
        <p className="text-xs">当前{textMode === 'original' ? '原始解析' : '清洗后'}文本没有文字。</p>
      </div>
    )
  } else if (parsedContent?.available === false && parsedContentError === null) {
    textPanelContent = (
      <div className="flex h-full items-center justify-center p-6">
        <div className="w-full max-w-md rounded-xl border border-border bg-background p-6 shadow-sm">
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-primary/10 p-2">
              <FileText className="size-5 text-primary" />
            </div>
            <div className="flex-1">
              <h4 className="text-sm font-semibold">暂无解析文本</h4>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                当前文档没有可读取的解析文本。可以重试读取，或查看已有切片和原文件。
              </p>
              <div className="mt-4 flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={onRetryParsedContent}>
                  重试读取文本
                </Button>
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
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-muted/20 dark:bg-muted/10">
      <div className="border-b border-border bg-background p-4">
        <div className="flex flex-col gap-2">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                size="sm"
                variant={textMode === 'cleaned' ? 'secondary' : 'outline'}
                aria-pressed={textMode === 'cleaned'}
                onClick={() => onTextModeChange('cleaned')}
              >
                清洗后
              </Button>
              <Button
                type="button"
                size="sm"
                variant={textMode === 'original' ? 'secondary' : 'outline'}
                aria-pressed={textMode === 'original'}
                onClick={() => onTextModeChange('original')}
              >
                原始解析
              </Button>

              {highlightChunkId && !loadAllChunks && !chunksLoaded ? (
                <span className="text-[11px] text-muted-foreground">
                  仅加载引用切片位置；如需展示全部切片位置，请点右侧「加载全部切片」。
                </span>
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
            <label htmlFor="document-viewer-retrieve-query" className="sr-only">
              检索测试问题
            </label>
            <input
              id="document-viewer-retrieve-query"
              value={retrieveQuery}
              onChange={(event) => onRetrieveQueryChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== 'Enter') return
                event.preventDefault()
                onRunRetrieve()
              }}
              placeholder="检索测试：输入问题，查看真实检索命中的切片…"
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
            <div className="flex items-center justify-end gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={!retrieveQuery.trim() || retrieveLoading}
                onClick={onRunRetrieve}
              >
                {getTextTabRetrieveButtonLabel(retrieveLoading)}
              </Button>
              {retrieveResultQuery !== null ? (
                <Button type="button" size="sm" variant="outline" onClick={onClearRetrieve}>
                  清空
                </Button>
              ) : null}
            </div>
          </div>

          {retrieveError !== null ? (
            <div
              role="alert"
              className="rounded-lg border border-destructive/25 bg-destructive/10 px-2 py-1 text-[11px] text-destructive"
            >
              <p>失败查询：{retrieveFailedQuery}</p>
              <p>{retrieveError}</p>
            </div>
          ) : null}

          {retrieveResultsPanel}

          {textMode === 'cleaned' && unpositionedChunkCount > 0 ? (
            <p className="text-xs text-muted-foreground">{unpositionedChunkCount} 个切片暂不能在正文中定位。</p>
          ) : null}

          {textMode === 'original' ? (
            <p className="text-[11px] text-muted-foreground">切换到「清洗后」可定位切片。</p>
          ) : null}

          {parsedContent !== null &&
          (textMode === 'original' ? parsedContent.original_markdown_truncated : parsedContent.markdown_truncated) ? (
            <div className="text-[11px] text-muted-foreground">
              文本已截断显示（max_chars={parsedContent.max_chars}）。如需完整内容，请提高
              persist_parsed_content_max_chars 或缩小文件。
            </div>
          ) : null}

          {parsedContentError !== null ? (
            <div
              role="alert"
              className="flex items-center justify-between gap-3 rounded-lg border border-destructive/25 bg-destructive/10 px-2 py-1 text-[11px] text-destructive"
            >
              <p className="min-w-0 break-words">{parsedContentError}</p>
              <Button size="sm" variant="ghost" disabled={parsedContentLoading} onClick={onRetryParsedContent}>
                重试读取文本
              </Button>
            </div>
          ) : null}
        </div>
      </div>

      <div className="flex-1 overflow-hidden p-4">{textPanelContent}</div>
    </div>
  )
}
