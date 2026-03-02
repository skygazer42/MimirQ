'use client'

import * as React from 'react'
import Image from 'next/image'
import { Copy, ExternalLink, FileText, Image as ImageIcon, Table2 } from 'lucide-react'
import { toast } from 'sonner'

import type { Citation } from '@/types'
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
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

function clampText(v: unknown, max = 240): string {
  const s = asText(v).trim()
  if (!s) return ''
  return s.length > max ? `${s.slice(0, max)}…` : s
}

function inferEvidenceKind(citation: Citation | null): 'image' | 'table' | 'text' {
  if (!citation) return 'text'
  const hitType = String((citation as any).hit_type || '').trim().toLowerCase()
  const chunkRole = String((citation as any).chunk_role || '').trim().toLowerCase()
  const semanticRole = String((citation as any).chunk_semantic_role || '').trim().toLowerCase()
  const hasImage = Boolean((citation as any).has_image)

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
    await navigator.clipboard.writeText(raw)
    return true
  } catch {
    // ignore
  }

  try {
    const textarea = document.createElement('textarea')
    textarea.value = raw
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.left = '0'
    textarea.style.top = '0'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.focus()
    textarea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textarea)
    return ok
  } catch {
    return false
  }
}

export function EvidenceViewerDialog({
  open,
  onOpenChange,
  citation,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  citation: Citation | null
}) {
  const { openDocument } = useDocumentView()

  const kind = inferEvidenceKind(citation)
  const imgUrl =
    kind === 'image' ? resolveSafeCitationImageUrl((citation as any)?.img_url) : null

  const title = (() => {
    if (!citation) return 'Evidence'
    const doc = clampText((citation as any).document_name || 'Document', 80)
    const p = (citation as any).page_number
    const pageLabel = typeof p === 'number' && p > 0 ? ` · P.${p}` : ''
    if (kind === 'image') return `Image Evidence · ${doc}${pageLabel}`
    if (kind === 'table') return `Table Evidence · ${doc}${pageLabel}`
    return `Evidence · ${doc}${pageLabel}`
  })()

  const onOpenInDoc = React.useCallback(() => {
    if (!citation?.document_id) return
    const start =
      typeof (citation as any).evidence_start_char === 'number'
        ? (citation as any).evidence_start_char
        : typeof (citation as any).start_char === 'number'
          ? (citation as any).start_char
          : null
    const end =
      typeof (citation as any).evidence_end_char === 'number'
        ? (citation as any).evidence_end_char
        : typeof (citation as any).end_char === 'number'
          ? (citation as any).end_char
          : null
    const range = start != null && end != null && end > start ? { start, end } : undefined
    openDocument(citation.document_id, (citation as any).chunk_id, range)
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

    push('document_id', (citation as any).document_id)
    push('chunk_id', (citation as any).chunk_id)
    push('page_number', (citation as any).page_number)
    push('chunk_index', (citation as any).chunk_index)
    push('span', (() => {
      const s = (citation as any).start_char
      const e = (citation as any).end_char
      if (typeof s === 'number' && typeof e === 'number' && e >= s) return `${s}..${e}`
      return ''
    })())
    push('evidence_span', (() => {
      const s = (citation as any).evidence_start_char
      const e = (citation as any).evidence_end_char
      if (typeof s === 'number' && typeof e === 'number' && e >= s) return `${s}..${e}`
      return ''
    })())
    push('hit_type', (citation as any).hit_type)
    push('retrieval_role', (citation as any).retrieval_role)
    push('neighbor_of', (citation as any).neighbor_of)
    push('doc_pipeline_key', (citation as any).doc_pipeline_key)
    push('pipeline_hash', (citation as any).pipeline_hash)
    push('retrieval_mode', (citation as any).retrieval_mode)
    push('reranker_provider', (citation as any).reranker_provider)
    push('relevance_score', (citation as any).relevance_score)
    push('vector_score', (citation as any).vector_score)
    push('bm25_score', (citation as any).bm25_score)
    push('keyword_score', (citation as any).keyword_score)
    push('rerank_score', (citation as any).rerank_score)
    push('retrieval_score', (citation as any).retrieval_score)
    push('retrieval_elapsed_sec', (citation as any).retrieval_elapsed_sec)
    push('rerank_elapsed_sec', (citation as any).rerank_elapsed_sec)

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
              {kind === 'image' ? (
                <span className="inline-flex items-center gap-1">
                  <ImageIcon className="h-3 w-3" />
                  image
                </span>
              ) : kind === 'table' ? (
                <span className="inline-flex items-center gap-1">
                  <Table2 className="h-3 w-3" />
                  table
                </span>
              ) : (
                <span className="inline-flex items-center gap-1">
                  <FileText className="h-3 w-3" />
                  text
                </span>
              )}
            </Badge>
            {citation?.document_name ? (
              <Badge variant="soft" className="text-[10px]" title={String(citation.document_name)}>
                {clampText(citation.document_name, 64)}
              </Badge>
            ) : null}
            {typeof (citation as any)?.page_number === 'number' ? (
              <Badge variant="soft" className="text-[10px]">
                P.{(citation as any).page_number}
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
                  {imgUrl ? (
                    <div className="relative w-full aspect-video">
                      <Image
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

                {imgUrl ? (
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-xl gap-2"
                      onClick={() => window.open(imgUrl, '_blank', 'noopener,noreferrer')}
                    >
                      <ExternalLink className="h-4 w-4" />
                      新窗口打开
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-xl gap-2"
                      onClick={async () => {
                        const ok = await copyToClipboard(imgUrl)
                        if (ok) toast.success('已复制图片 URL')
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

