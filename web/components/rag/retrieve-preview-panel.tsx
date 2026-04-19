'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Copy,
  Database,
  ExternalLink,
  File as FileIcon,
  FileStack,
  Loader2,
  Search,
  Sparkles,
  TestTube2,
  Zap,
  ChevronDown,
  ChevronRight,
  Maximize2,
  X,
} from 'lucide-react'
import type {
  Citation,
  EvidenceRetrieveResponse,
  ReferenceSource,
  RegressionCaseCreate,
} from '@/types'
import { AuthImage, AuthImageLink, useResolvedAuthAssetUrl } from '@/components/auth-image'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { IconButton } from '@/components/ui/icon-button'
import { Kbd } from '@/components/ui/kbd'
import { Panel } from '@/components/ui/panel'
import { formatApiError } from '@/lib/api-errors'
import { resolveSafeCitationImageUrl } from '@/lib/citation-images'
import { getDocumentPreviewAnchorFromCitation } from '@/lib/document-preview-anchor'
import { prefetchDocumentView } from '@/lib/document-view-prefetch'
import { cn, detachPromise } from '@/lib/utils'
import { evaluationApi, ragApi } from '@/lib/api'
import { useDocumentView } from '@/store/document-view'
import { toast } from 'sonner'
import { motion, AnimatePresence } from 'framer-motion'

type RetrievePreviewPanelProps = {
  selectedDatasetId: string | null | undefined
  className?: string
}

type JsonRecord = Record<string, unknown>

interface RetrievePreviewCitation extends Citation {
  retrieval_role?: string
  family_hit?: boolean
  family_collapse_key?: string
  hierarchy_family_key?: string
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function formatScore(value: unknown, digits = 3): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—'
}

function toHitKey(hit: Pick<RetrievePreviewCitation, 'document_id' | 'chunk_id' | 'retrieval_role'>): string {
  return [
    String(hit.document_id || '').trim(),
    String(hit.chunk_id || '').trim(),
    String(hit.retrieval_role || '').trim(),
  ].join(':')
}

function previewChunkContent(value: string | undefined, maxLen = 360): string {
  const text = String(value || '').trim().replaceAll(/\s+/g, ' ')
  if (!text) return '该命中未返回可预览的 chunk 内容。'
  if (text.length <= maxLen) return text
  return `${text.slice(0, maxLen).trimEnd()}…`
}

const noResultActionTips = ['缩短问题', '切换数据集', '改用原文关键词', '补充条款编号'] as const
const noResultDiagnosticTips = [
  { title: '问题过长或太泛', description: '先压缩成一个核心问题，减少背景描述和泛化措辞。' },
  { title: '检索范围过窄', description: '切到更大的数据集范围，确认文档已解析。' },
  { title: '表达不贴近原文', description: '优先使用条款编号、章节名、专有名词和原句关键词。' },
] as const

export function RetrievePreviewPanel({ selectedDatasetId, className }: Readonly<RetrievePreviewPanelProps>) {
  const { openDocument } = useDocumentView()
  const [searchQuery, setSearchQuery] = useState('')
  const [hasSearched, setHasSearched] = useState(false)
  const [searchResults, setSearchResults] = useState<RetrievePreviewCitation[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const searchInputRef = useRef<HTMLTextAreaElement | null>(null)
  
  const [activeHit, setActiveHit] = useState<RetrievePreviewCitation | null>(null)

  const handleSearch = async () => {
    const q = searchQuery.trim()
    if (!q || isSearching) return

    setIsSearching(true)
    setSearchError(null)
    try {
      const res = await ragApi.retrieve({
        query: q,
        dataset_id: selectedDatasetId || undefined,
        limit: 10,
      })
      setSearchResults(res.citations || [])
      setHasSearched(true)
      if (res.citations?.length > 0) setActiveHit(res.citations[0])
    } catch (err) {
      setSearchError(formatApiError(err, '检索失败'))
    } finally {
      setIsSearching(false)
    }
  }

  const resetSearch = () => {
    setHasSearched(false)
    setSearchResults([])
    setSearchQuery('')
    setSearchError(null)
  }

  return (
    <div className={cn("relative flex h-full flex-col overflow-hidden bg-background/50", className)}>
      {/* 沉浸式背景：径向环境光场 */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden z-0">
        <div className="absolute top-[40%] left-1/2 -translate-x-1/2 -translate-y-1/2 size-[600px] bg-primary/10 rounded-full blur-[100px] opacity-30" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,transparent_0%,var(--background)_80%)]" />
        <div className="absolute inset-0 opacity-[0.03] bg-[grid-size:40px_40px] bg-[linear-gradient(to_right,#808080_1px,transparent_1px),linear-gradient(to_bottom,#808080_1px,transparent_1px)]" />
      </div>

      <div className="relative flex-1 flex flex-col z-10">
        {!hasSearched && !isSearching ? (
          <div className="flex-1 flex flex-col items-center justify-center px-6 pb-24">
            <motion.div initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-2xl text-center space-y-10">
              <div className="space-y-4">
                <div className="inline-flex size-14 items-center justify-center rounded-[2rem] bg-primary/10 border border-primary/20 shadow-strong text-primary">
                  <Sparkles className="size-7" />
                </div>
                <div className="space-y-2">
                  <h2 className="text-2xl font-black tracking-tight text-foreground">语义检索测试</h2>
                  <p className="text-sm font-medium text-muted-foreground/60 max-w-sm mx-auto leading-relaxed">
                    输入复杂问题或长 Prompt，验证 RAG 的召回质量和调试指标。
                  </p>
                </div>
              </div>

              <div className="relative group">
                <div className="absolute -inset-1 bg-gradient-to-r from-primary/10 to-indigo-500/10 rounded-[2.5rem] blur opacity-0 group-focus-within:opacity-100 transition duration-1000" />
                <div className="relative flex flex-col gap-4 rounded-[2.25rem] border border-border/60 bg-background/70 p-6 shadow-[0_20px_50px_rgba(0,0,0,0.1)] backdrop-blur-3xl ring-1 ring-white/5">
                  <div className="flex gap-4 items-start">
                    <Search className="size-5 mt-1.5 text-muted-foreground/30 group-focus-within:text-primary transition-colors" />
                    <textarea
                      ref={searchInputRef}
                      className="flex-1 bg-transparent border-0 p-0 text-base font-medium placeholder:text-muted-foreground/30 focus:ring-0 min-h-[90px] resize-none scroll-smooth"
                      placeholder="例如：请按第十二条说明例外条件，并指出适用范围与例外条款"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSearch(); } }}
                    />
                  </div>
                  
                  <div className="flex items-center justify-between pt-3 border-t border-border/20">
                    <div className="flex items-center gap-3">
                      <div className="flex items-center gap-2 px-2.5 py-1 rounded-full bg-muted/40 border border-border/40">
                        <Database className="size-3 text-muted-foreground/40" />
                        <span className="text-[11px] font-bold text-foreground/70">{selectedDatasetId || '全部数据集'}</span>
                      </div>
                      <div className="hidden sm:flex items-center gap-2 opacity-30">
                        <div className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-border/60 text-[9px] font-bold text-muted-foreground"><Kbd className="h-3 border-0 bg-transparent p-0 text-[9px]">Enter</Kbd><span>发送</span></div>
                        <div className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-border/60 text-[9px] font-bold text-muted-foreground"><Kbd className="h-3 border-0 bg-transparent p-0 text-[9px]">⇧</Kbd><Kbd className="h-3 border-0 bg-transparent p-0 text-[9px]">Enter</Kbd><span>换行</span></div>
                      </div>
                    </div>
                    <Button onClick={handleSearch} disabled={!searchQuery.trim()} className="h-10 rounded-xl px-7 bg-primary text-primary-foreground font-black shadow-lg shadow-primary/20 hover:scale-[1.02] active:scale-[0.98] transition-all">开始检索</Button>
                  </div>
                </div>
              </div>
            </motion.div>
          </div>
        ) : (
          <div className="flex-1 flex flex-col min-h-0">
            {/* 检索结果展示逻辑... (此处保持原有结果展示，但外层已去容器化) */}
            <div className="mx-auto w-full max-w-6xl px-6 py-6 space-y-6">
               <div className="flex items-center justify-between">
                 <Button variant="ghost" onClick={resetSearch} className="h-9 rounded-xl text-muted-foreground hover:text-foreground">
                   <X className="mr-2 size-4" /> 重新检索
                 </Button>
               </div>
               
               {isSearching ? (
                 <div className="space-y-4 animate-pulse">
                   {[0,1,2].map(i => <div key={i} className="h-32 bg-muted/20 rounded-[2rem] border border-border/40" />)}
                 </div>
               ) : searchError ? (
                 <div className="p-6 rounded-2xl bg-destructive/5 border border-destructive/10 text-destructive text-sm">{searchError}</div>
               ) : searchResults.length === 0 ? (
                 <div className="text-center py-20 opacity-40 font-bold uppercase tracking-widest">No Results Found</div>
               ) : (
                 <div className="grid gap-6">
                   {searchResults.map((hit, idx) => (
                     <div key={idx} className="p-6 rounded-[2.25rem] border border-border/40 bg-card/40 backdrop-blur-md shadow-soft">
                        <div className="flex items-center gap-3 mb-4">
                          <div className="size-8 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-[11px] font-black text-primary">#{idx+1}</div>
                          <span className="text-sm font-bold text-foreground/90 truncate">{hit.document_name}</span>
                          <Badge variant="outline" className="ml-auto tabular-nums">Score: {formatScore(hit.score)}</Badge>
                        </div>
                        <p className="text-sm leading-relaxed text-muted-foreground/80 line-clamp-4">{hit.chunk_content}</p>
                     </div>
                   ))}
                 </div>
               )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
