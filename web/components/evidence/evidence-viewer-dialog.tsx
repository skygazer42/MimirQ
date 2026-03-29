'use client'

import * as React from 'react'
import { Copy, ExternalLink, FileText, Image as ImageIcon, Table2 } from 'lucide-react'
import { toast } from 'sonner'

import { AuthImage, useResolvedAuthAssetUrl } from '@/components/auth-image'
import type { Citation } from '@/types'
import { getDocumentPreviewAnchorFromCitation } from '@/lib/document-preview-anchor'
import { toPrimitiveString } from '@/lib/primitive-text'
import { cn } from '@/lib/utils'
import { resolveSafeCitationImageUrl } from '@/lib/citation-images'
import { useDocumentView } from '@/store/document-view'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'

function asText(v: unknown): string {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean' || typeof v === 'bigint' || typeof v === 'symbol') return toPrimitiveString(v)
  try {
    return JSON.stringify(v)
  } catch {
    return ''
  }
}

function clampText(v: unknown, max = 240): string {
  const s = asText(v).trim()
  if (!s) return ''
  return s.length > max ? `${s.slice(0, max)}…` : s
}

function inferEvidenceKind(citation: Citation | null): 'image' | 'table' | 'text' {
  if (!citation) return 'text'
  const hitType = String(citation.hit_type || '').trim().toLowerCase()
  const chunkRole = String(citation.chunk_role || '').trim().toLowerCase()
  const semanticRole = String(citation.chunk_semantic_role || '').trim().toLowerCase()
  const hasImage = Boolean(citation.has_image)

  if (hasImage || hitType === 'image') return 'image'
  if (
    hitType === 'tag' ||
    hitType === 'table' ||
    chunkRole.includes('tag') ||
    chunkRole.includes('table') ||
    semanticRole === 'table'
  ) {
    return 'table'
  }
  return 'text'
}

async function copyToClipboard(text: string) {
  const raw = String(text || '')
  if (!raw) return false

  try {
    if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) return false
    await navigator.clipboard.writeText(raw)
    return true
  } catch {
    return false
  }
}

export function EvidenceViewerDialog({
  open,
  onOpenChange,
  citation,
}: Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  citation: Citation | null
}>) {
  const { openDocument } = useDocumentView()

  const kind = inferEvidenceKind(citation)
  const imgUrl = kind === 'image' ? resolveSafeCitationImageUrl(citation?.img_url) : null
  const resolvedImgUrl = useResolvedAuthAssetUrl(imgUrl)

  const title = (() => {
    if (!citation) return 'Evidence'
    const doc = clampText(citation.document_name || 'Document', 80)
    const p = citation.page_number
    const pageLabel = typeof p === 'number' && p > 0 ? ` · P.${p}` : ''
    if (kind === 'image') return `Image Evidence · ${doc}${pageLabel}`
    if (kind === 'table') return `Table Evidence · ${doc}${pageLabel}`
    return `Evidence · ${doc}${pageLabel}`
  })()

  const onOpenInDoc = React.useCallback(() => {
    if (!citation?.document_id) return
    const start =
      (() => {
    if (typeof citation.evidence_start_char === 'number') {
        return citation.evidence_start_char;
    }
    else if (typeof citation.start_char === 'number') {
            return citation.start_char;
        }
        else {
            return null;
        }
})()
    const end =
      (() => {
    if (typeof citation.evidence_end_char === 'number') {
        return citation.evidence_end_char;
    }
    else if (typeof citation.end_char === 'number') {
            return citation.end_char;
        }
        else {
            return null;
        }
})()
    const range = start != null && end != null && end > start ? { start, end } : undefined
    openDocument(citation.document_id, citation.chunk_id, range, {
      previewAnchor: getDocumentPreviewAnchorFromCitation(citation),
    })
  }, [citation, openDocument])

  const onCopyJson = React.useCallback(async () => {
    if (!citation) return
    const ok = await copyToClipboard(JSON.stringify(citation, null, 2))
    if (ok) toast.success('已复制证据信息（JSON）')
  }, [citation])

  const meta = React.useMemo(() => {
    if (!citation) return []

    const rows: Array<{ k: string; v: string }> = []
    const push = (k: string, v: unknown) => {
      const s = clampText(v, 260)
      if (!s) return
      rows.push({ k, v: s })
    }

    push('document_id', citation.document_id)
    push('chunk_id', citation.chunk_id)
    push('page_number', citation.page_number)
    push('chunk_index', citation.chunk_index)
    push('span', (() => {
      const s = citation.start_char
      const e = citation.end_char
      if (typeof s === 'number' && typeof e === 'number' && e >= s) return `${s}..${e}`
      return ''
    })())
    push('evidence_span', (() => {
      const s = citation.evidence_start_char
      const e = citation.evidence_end_char
      if (typeof s === 'number' && typeof e === 'number' && e >= s) return `${s}..${e}`
      return ''
    })())
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
      <DialogContent className="max-w-3xl p-0 overflow-hidden">
        <DialogHeader className="px-4 py-3 border-b border-border/60">
          <DialogTitle className="text-sm">{title}</DialogTitle>
        </DialogHeader>

        <div className="px-4 py-3 flex flex-wrap items-center justify-between gap-2 border-b border-border/40">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="soft" className="text-[10px]">
              {(() => {
    if (kind === 'image') {
        return (<span className="inline-flex items-center gap-1">
                  <ImageIcon className="h-3 w-3"/>
                  image
                </span>);
    }
    else if (kind === 'table') {
            return (<span className="inline-flex items-center gap-1">
                  <Table2 className="h-3 w-3"/>
                  table
                </span>);
        }
        else {
            return (<span className="inline-flex items-center gap-1">
                  <FileText className="h-3 w-3"/>
                  text
                </span>);
        }
})()}
            </Badge>
            {citation?.document_name ? (
              <Badge variant="soft" className="text-[10px]" title={String(citation.document_name)}>
                {clampText(citation.document_name, 64)}
              </Badge>
            ) : null}
            {typeof citation?.page_number === 'number' ? (
              <Badge variant="soft" className="text-[10px]">
                P.{citation.page_number}
              </Badge>
            ) : null}
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="rounded-xl gap-2"
              onClick={onCopyJson}
              disabled={!citation}
            >
              <Copy className="h-4 w-4" />
              复制 JSON
            </Button>
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

        <ScrollArea className="max-h-[70vh]">
          <div className="p-4 space-y-4">
            {kind === 'image' ? (
              <div className="space-y-3">
                <div className="rounded-xl border border-border/60 bg-muted/20 overflow-hidden">
                  {resolvedImgUrl ? (
                    <div className="relative w-full aspect-video">
                      <AuthImage
                        src={imgUrl}
                        alt="evidence image"
                        fill
                        unoptimized
                        sizes="(max-width: 768px) 100vw, 900px"
                        className="object-contain bg-background"
                      />
                    </div>
                  ) : (
                    <div className="p-6 text-sm text-muted-foreground">
                      无法加载图片预览（URL 不安全或缺失）。
                    </div>
                  )}
                </div>

                {resolvedImgUrl ? (
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-xl gap-2"
                      onClick={() => globalThis.window.open(resolvedImgUrl, '_blank', 'noopener,noreferrer')}
                    >
                      <ExternalLink className="h-4 w-4" />
                      新窗口打开
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-xl gap-2"
                      onClick={async () => {
                        const ok = await copyToClipboard(resolvedImgUrl)
                        if (ok) toast.success('已复制临时图片链接')
                      }}
                    >
                      <Copy className="h-4 w-4" />
                      复制 URL
                    </Button>
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
                    'text-xs leading-relaxed overflow-auto whitespace-pre-wrap'
                  )}
                >
                  {String(citation.chunk_content)}
                </pre>
              </div>
            ) : null}

            {meta.length ? (
              <div className="space-y-2">
                <div className="text-xs font-semibold text-foreground">Provenance</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {meta.map((row) => (
                    <div
                      key={row.k}
                      className="rounded-xl border border-border/60 bg-card px-3 py-2"
                    >
                      <div className="text-[10px] font-bold text-muted-foreground uppercase">
                        {row.k}
                      </div>
                      <div className="mt-1 text-xs font-mono text-foreground break-words">
                        {row.v}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  )
}
