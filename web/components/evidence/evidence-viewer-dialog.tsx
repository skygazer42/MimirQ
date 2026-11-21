'use client'

import { workspaceStyles as ws } from '@/components/ui/operational-workspace'
import * as React from 'react'
import { Copy, ExternalLink, FileText, Image as ImageIcon, Table2 } from '@/components/icons'
import { toast } from 'sonner'

import Image from 'next/image'
import { useAuthAsset } from '@/components/auth-image'
import { Skeleton } from '@/components/ui/skeleton'
import type { Citation } from '@/types'
import { getDocumentPreviewAnchorFromCitation } from '@/lib/document-preview-anchor'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { formatApiError } from '@/lib/api-errors'
import { cn } from '@/lib/utils'
import { resolveSafeCitationImageUrl } from '@/lib/citation-images'
import type { DocumentViewSourceContext } from '@/store/document-view'
import { useDocumentView } from '@/store/document-view'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'

type EvidenceViewerCitation = { [Field in keyof Citation]?: Citation[Field] | null }

function inferEvidenceKind(citation: EvidenceViewerCitation | null): 'image' | 'table' | 'text' {
  if (citation === null) return 'text'
  const hitType = citation.hit_type?.trim().toLowerCase()
  const chunkRole = citation.chunk_role?.trim().toLowerCase()
  const semanticRole = citation.chunk_semantic_role?.trim().toLowerCase()
  if (citation.has_image === true || hitType === 'image') return 'image'
  if (
    hitType === 'tag' ||
    hitType === 'table' ||
    chunkRole?.includes('tag') ||
    chunkRole?.includes('table') ||
    semanticRole === 'table'
  )
    return 'table'
  return 'text'
}

function spanLabel(start: number | null | undefined, end: number | null | undefined): string | undefined {
  return start !== undefined && start !== null && end !== undefined && end !== null && end >= start
    ? `${start}..${end}`
    : undefined
}

export function EvidenceViewerDialog({
  open,
  onOpenChange,
  citation,
  sourceContext,
}: Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  citation: EvidenceViewerCitation | null
  sourceContext?: DocumentViewSourceContext | null
}>) {
  const { openDocument } = useDocumentView()

  const kind = inferEvidenceKind(citation)
  const imgUrl = kind === 'image' ? resolveSafeCitationImageUrl(citation?.img_url) : null
  const { state: imageState, retry: retryImage, reportImageError } = useAuthAsset(imgUrl, { enabled: open })
  const resolvedImgUrl = imageState.status === 'ready' ? imageState.url : null

  const sessionKey = React.useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const activeCopy = React.useRef<object | null>(null)
  const [copying, setCopying] = React.useState<'json' | 'url' | null>(null)
  const [copyError, setCopyError] = React.useState<string | null>(null)
  React.useLayoutEffect(() => {
    activeCopy.current = null
    setCopying(null)
    setCopyError(null)
    return () => {
      activeCopy.current = null
    }
  }, [open, citation, sessionKey])

  const kindTitle = kind === 'image' ? 'Image Evidence' : kind === 'table' ? 'Table Evidence' : 'Evidence'
  const EvidenceIcon = kind === 'image' ? ImageIcon : kind === 'table' ? Table2 : FileText
  const pageLabel =
    citation?.page_number === undefined || citation.page_number === null ? '' : ` · P.${citation.page_number}`
  const documentLabel = citation?.document_name ? ` · ${citation.document_name}` : ''
  const title = citation === null ? 'Evidence' : `${kindTitle}${documentLabel}${pageLabel}`

  function onOpenInDoc() {
    if (!citation?.document_id) return
    const start = citation.evidence_start_char ?? citation.start_char
    const end = citation.evidence_end_char ?? citation.end_char
    const range =
      start !== undefined && start !== null && end !== undefined && end !== null && end > start
        ? { start, end }
        : undefined
    openDocument(citation.document_id, citation.chunk_id ?? undefined, range, {
      previewAnchor: getDocumentPreviewAnchorFromCitation(citation),
      sourceContext,
    })
  }

  async function copy(text: string, target: 'json' | 'url', successMessage: string) {
    if (!open || activeCopy.current !== null) return
    const operation = {}
    activeCopy.current = operation
    setCopying(target)
    setCopyError(null)
    const isCurrent = () => activeCopy.current === operation && getAuthSessionKey() === sessionKey
    try {
      if (navigator.clipboard === undefined) throw new Error('当前浏览器环境不支持剪贴板')
      await navigator.clipboard.writeText(text)
      if (isCurrent()) toast.success(successMessage)
    } catch (error: unknown) {
      if (isCurrent()) setCopyError(`复制失败：${formatApiError(error, '无法访问剪贴板')}`)
    } finally {
      if (isCurrent()) {
        activeCopy.current = null
        setCopying(null)
      }
    }
  }

  function onCopyJson() {
    if (citation === null) return
    void copy(JSON.stringify(citation, null, 2), 'json', '已复制证据信息（JSON）')
  }

  const meta = React.useMemo(() => {
    if (!citation) return []

    const rows: Array<{ key: string; value: string }> = []
    const push = (key: string, value: string | number | null | undefined) => {
      if (value === undefined || value === null) return
      rows.push({ key, value: String(value) })
    }

    push('document_id', citation.document_id)
    push('chunk_id', citation.chunk_id)
    push('page_number', citation.page_number)
    push('chunk_index', citation.chunk_index)
    push('span', spanLabel(citation.start_char, citation.end_char))
    push('evidence_span', spanLabel(citation.evidence_start_char, citation.evidence_end_char))
    push('hit_type', citation.hit_type)
    push('retrieval_role', citation.retrieval_role)
    push('neighbor_of', citation.neighbor_of)
    push('doc_pipeline_key', citation.doc_pipeline_key)
    push('pipeline_hash', citation.pipeline_hash)
    push('retrieval_mode', citation.retrieval_mode)
    push('reranker_provider', citation.reranker_provider)
    push('relevance_score', citation.relevance_score)
    push('vector_score', citation.vector_score)
    push('bm25_score', citation.bm25_score)
    push('keyword_score', citation.keyword_score)
    push('rerank_score', citation.rerank_score)
    push('retrieval_score', citation.retrieval_score)
    push('retrieval_elapsed_sec', citation.retrieval_elapsed_sec)
    push('rerank_elapsed_sec', citation.rerank_elapsed_sec)

    return rows
  }, [citation])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={ws.dialog} aria-describedby={undefined}>
        <DialogHeader className={ws.dialogHeader}>
          <DialogTitle className="line-clamp-2 break-words text-sm" title={title}>
            {title}
          </DialogTitle>
        </DialogHeader>
        <div className={ws.dialogBody}>
          <div className="px-4 py-3 flex flex-wrap items-center justify-between gap-2 border-b border-border/40">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="soft" className="text-[11px]">
                <span className="inline-flex items-center gap-1">
                  <EvidenceIcon className="h-3 w-3" />
                  {kind}
                </span>
              </Badge>
              {citation?.document_name ? (
                <Badge variant="soft" className="text-[11px]" title={citation.document_name}>
                  <span className="max-w-64 truncate">{citation.document_name}</span>
                </Badge>
              ) : null}
              {typeof citation?.page_number === 'number' ? (
                <Badge variant="soft" className="text-[11px]">
                  P.{citation.page_number}
                </Badge>
              ) : null}
            </div>

            <div className="flex items-center gap-2">
              <LoadingButton
                loading={copying === 'json'}
                variant="outline"
                size="sm"
                className="rounded-xl gap-2"
                onClick={onCopyJson}
                disabled={citation === null || copying !== null}
              >
                <Copy className="h-4 w-4" />
                复制 JSON
              </LoadingButton>
              <Button
                variant="default"
                size="sm"
                className="rounded-xl"
                onClick={onOpenInDoc}
                disabled={!citation?.document_id}
              >
                打开文档
              </Button>
            </div>
          </div>

          {copyError !== null ? (
            <p role="alert" className="px-4 py-3 break-words text-sm text-destructive">
              {copyError}。可重试复制。
            </p>
          ) : null}
          <ScrollArea className="max-h-[70vh]">
            <div className="p-4 space-y-4">
              {kind === 'image' ? (
                <div className="space-y-3">
                  <div className="rounded-xl border border-border/60 bg-muted/20 overflow-hidden">
                    {resolvedImgUrl ? (
                      <div className="relative w-full aspect-video">
                        <Image
                          src={resolvedImgUrl}
                          onError={() => reportImageError(resolvedImgUrl)}
                          alt="evidence image"
                          fill
                          unoptimized
                          sizes="(max-width: 768px) 100vw, 900px"
                          className="object-contain bg-background"
                        />
                      </div>
                    ) : imageState.status === 'loading' ? (
                      <div role="status" aria-label="正在读取证据图片" className="aspect-video">
                        <Skeleton className="h-full w-full rounded-none" />
                      </div>
                    ) : imageState.status === 'error' ? (
                      <div className="space-y-3 p-4">
                        <p role="alert" className="break-words text-sm text-muted-foreground">
                          图片读取失败：{imageState.message}
                        </p>
                        <Button type="button" variant="outline" size="sm" onClick={retryImage}>
                          重试读取图片
                        </Button>
                      </div>
                    ) : (
                      <div className="p-6 text-sm text-muted-foreground">无法加载图片预览（URL 不安全或缺失）。</div>
                    )}
                  </div>

                  {resolvedImgUrl ? (
                    <div className="flex items-center gap-2">
                      <Button variant="outline" size="sm" className="rounded-xl gap-2" asChild>
                        <a href={resolvedImgUrl} target="_blank" rel="noopener noreferrer">
                          <ExternalLink className="h-4 w-4" />
                          新窗口打开
                        </a>
                      </Button>
                      <LoadingButton
                        loading={copying === 'url'}
                        disabled={copying !== null}
                        variant="outline"
                        size="sm"
                        className="rounded-xl gap-2"
                        onClick={() => void copy(resolvedImgUrl, 'url', '已复制临时图片链接')}
                      >
                        <Copy className="h-4 w-4" />
                        复制 URL
                      </LoadingButton>
                    </div>
                  ) : null}
                </div>
              ) : null}

              {citation?.chunk_content ? (
                <div className="space-y-2">
                  <div className="text-xs font-semibold text-foreground">Evidence Snippet</div>
                  <pre
                    className={cn(
                      'rounded-xl border border-border/60 bg-muted/20 p-3',
                      'text-xs leading-relaxed overflow-auto whitespace-pre-wrap',
                    )}
                  >
                    {citation.chunk_content}
                  </pre>
                </div>
              ) : null}

              {meta.length ? (
                <div className="space-y-2">
                  <div className="text-xs font-semibold text-foreground">Provenance</div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {meta.map((row) => (
                      <div key={row.key} className="rounded-xl border border-border/60 bg-card px-3 py-2">
                        <div className="text-[11px] font-bold text-muted-foreground uppercase">{row.key}</div>
                        <div className="mt-1 text-xs font-mono text-foreground break-words">{row.value}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </ScrollArea>
        </div>
      </DialogContent>
    </Dialog>
  )
}
