/**
 * ChunkList - 切片列表
 */
'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Layers, MousePointer2, Loader2, AlertCircle, Search, CornerDownLeft, Copy, Braces, Code2, Quote, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { ChunkCard } from '../../chunk-card'
import type { ChunkPreviewItem } from '@/types'

const QUERY_DEBOUNCE_MS = 150
type SortMode = 'index' | 'length_desc' | 'length_asc'
const PAGE_ALL_VALUE = '__mimirq_page_all__'
const PAGE_UNKNOWN_VALUE = '__mimirq_page_unknown__'

function isEditableTarget(target: EventTarget | null) {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = (el.tagName || '').toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true
  return el.isContentEditable
}

export function ChunkList() {
  const {
    previewData,
    hoveredChunkIndex,
    selectedChunkIndex,
    setHoveredChunkIndex,
    setSelectedChunkIndex,
    showOriginalPanel,
    isLoading,
    error,
    runPreview,
  } = useChunkPreview()
  const unit: 'chars' | 'tokens' = previewData?.params?.unit === 'tokens' ? 'tokens' : 'chars'
  const [queryInput, setQueryInput] = useState('')
  const [query, setQuery] = useState('')
  const [sortMode, setSortMode] = useState<SortMode>('index')
  const [pageFilter, setPageFilter] = useState<string>(PAGE_ALL_VALUE)
  const [minLen, setMinLen] = useState<number>(0)
  const [maxLen, setMaxLen] = useState<number>(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const t = window.setTimeout(() => setQuery(queryInput), QUERY_DEBOUNCE_MS)
    return () => window.clearTimeout(t)
  }, [queryInput])

  useEffect(() => {
    setPageFilter(PAGE_ALL_VALUE)
    setQueryInput('')
    setQuery('')
    setSortMode('index')
    setMinLen(0)
    setMaxLen(0)
  }, [previewData?.filename])

  const pageOptions = useMemo(() => {
    const chunks = previewData?.chunks || []
    const pages = new Set<number>()
    let hasUnknown = false
    for (const c of chunks) {
      if (typeof c.page_number === 'number') pages.add(c.page_number)
      else hasUnknown = true
    }
    const list = Array.from(pages).sort((a, b) => a - b)
    return { list, hasUnknown }
  }, [previewData?.chunks])

  const selectedChunk = useMemo(() => {
    if (!previewData?.chunks || selectedChunkIndex == null) return null
    return previewData.chunks[selectedChunkIndex] || null
  }, [previewData?.chunks, selectedChunkIndex])

  const selectedChunkLenLabel = useMemo(() => {
    if (!selectedChunk) return null
    const tok = typeof selectedChunk.tokens_est === 'number' ? selectedChunk.tokens_est : null
    if (unit === 'tokens') return `${tok ?? '-'} tok · ${selectedChunk.length} chars`
    return tok != null ? `${selectedChunk.length} chars · ${tok} tok` : `${selectedChunk.length} chars`
  }, [selectedChunk, unit])

  const filteredChunks = useMemo(() => {
    if (!previewData?.chunks) return []
    const readLen = (chunk: ChunkPreviewItem) => {
      if (unit === 'tokens') return Number(chunk.tokens_est || 0)
      return Number(chunk.length || 0)
    }
    const q = query.trim().toLowerCase()
    const base = previewData.chunks
      .map((chunk: ChunkPreviewItem, index: number) => ({ chunk, index }))
      .filter(({ chunk }: { chunk: ChunkPreviewItem }) => {
        if (pageFilter === PAGE_ALL_VALUE) {
          // pass
        } else if (pageFilter === PAGE_UNKNOWN_VALUE) {
          if (typeof chunk.page_number === 'number') return false
        } else {
          if (String(chunk.page_number ?? '') !== pageFilter) return false
        }

        const contentOk = q ? (chunk.content || '').toLowerCase().includes(q) : true
        if (!contentOk) return false

        const len = readLen(chunk)
        if (minLen > 0 && len < minLen) return false
        if (maxLen > 0 && len > maxLen) return false

        return true
      })

    if (sortMode === 'length_desc') {
      base.sort((a, b) => readLen(b.chunk) - readLen(a.chunk))
    } else if (sortMode === 'length_asc') {
      base.sort((a, b) => readLen(a.chunk) - readLen(b.chunk))
    }
    return base
  }, [previewData, pageFilter, query, sortMode, minLen, maxLen, unit])

  const rowVirtualizer = useVirtualizer({
    count: filteredChunks.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 140,
    overscan: 8,
  })

  // Keep the selected chunk visible (best effort).
  useEffect(() => {
    if (selectedChunkIndex == null) return
    const pos = filteredChunks.findIndex((item) => item.index === selectedChunkIndex)
    if (pos >= 0) {
      rowVirtualizer.scrollToIndex(pos, { align: 'center' })
    }
  }, [filteredChunks, rowVirtualizer, selectedChunkIndex])

  const matchesLabel = useMemo(() => {
    const hasFilter =
      Boolean(query.trim()) ||
      pageFilter !== PAGE_ALL_VALUE ||
      minLen > 0 ||
      maxLen > 0
    if (!hasFilter) return null
    return `${filteredChunks.length} / ${previewData?.total_chunks || 0}`
  }, [filteredChunks.length, previewData?.total_chunks, query, pageFilter, minLen, maxLen])

  const showVirtualized = Boolean(previewData?.chunks && filteredChunks.length > 0)

  const copyText = async (value: string, okMessage: string) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value)
        toast.success(okMessage)
        return
      }
    } catch {
      // ignore
    }
    toast.error('复制失败：浏览器不支持 Clipboard API')
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-background/60">
      <div className="h-12 border-b border-border/60 bg-card/80 flex items-center justify-between px-4 shrink-0 gap-3 backdrop-blur">
        <span className="text-xs font-semibold text-primary flex items-center gap-2">
          <Layers className="w-3.5 h-3.5" />
          切片列表
          {previewData?.total_chunks ? (
            <span className="text-[10px] text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded-full">
              {previewData.total_chunks}
            </span>
          ) : null}
        </span>
        <div className="flex items-center gap-2 flex-1 justify-end">
          <div className="relative w-48">
            <Search className="w-3.5 h-3.5 text-muted-foreground absolute left-2 top-1/2 -translate-y-1/2" />
            <Input
              ref={searchRef}
              value={queryInput}
              onChange={(e) => setQueryInput(e.target.value)}
              placeholder="搜索切片内容..."
              className="h-7 pl-7 pr-7 text-[11px] bg-card/80"
            />
            {queryInput ? (
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors focus-ring rounded"
                onClick={() => {
                  setQueryInput('')
                  setQuery('')
                }}
                aria-label="清除搜索"
                title="清除搜索"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            ) : null}
          </div>
          <Select value={sortMode} onValueChange={(value) => setSortMode(value as SortMode)}>
            <SelectTrigger className="h-7 w-[140px] text-[11px] bg-card/80">
              <SelectValue placeholder="排序" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="index">原顺序</SelectItem>
              <SelectItem value="length_desc">{unit === 'tokens' ? 'Tokens：大到小' : '长度：大到小'}</SelectItem>
              <SelectItem value="length_asc">{unit === 'tokens' ? 'Tokens：小到大' : '长度：小到大'}</SelectItem>
            </SelectContent>
          </Select>
          <Select value={pageFilter} onValueChange={(value) => setPageFilter(value)}>
            <SelectTrigger className="h-7 w-[110px] text-[11px] bg-card/80">
              <SelectValue placeholder="页面" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={PAGE_ALL_VALUE}>全部页面</SelectItem>
              {pageOptions.hasUnknown ? <SelectItem value={PAGE_UNKNOWN_VALUE}>未知</SelectItem> : null}
              {pageOptions.list.map((p) => (
                <SelectItem key={p} value={String(p)}>
                  P.{p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="hidden xl:flex items-center gap-1 text-[10px] text-muted-foreground">
            <span className="mr-1">{unit === 'tokens' ? 'Tokens:' : '长度:'}</span>
            <Input
              value={minLen > 0 ? String(minLen) : ''}
              onChange={(e) => {
                const raw = e.target.value.trim()
                const n = raw ? Number(raw) : 0
                if (!raw) setMinLen(0)
                else if (Number.isFinite(n)) setMinLen(Math.max(0, Math.trunc(n)))
              }}
              placeholder="Min"
              className="h-7 w-[72px] text-[11px] font-mono bg-card/80"
              inputMode="numeric"
              aria-label={unit === 'tokens' ? '最小 token 过滤' : '最小长度过滤'}
            />
            <span className="px-1 opacity-70">-</span>
            <Input
              value={maxLen > 0 ? String(maxLen) : ''}
              onChange={(e) => {
                const raw = e.target.value.trim()
                const n = raw ? Number(raw) : 0
                if (!raw) setMaxLen(0)
                else if (Number.isFinite(n)) setMaxLen(Math.max(0, Math.trunc(n)))
              }}
              placeholder="Max"
              className="h-7 w-[72px] text-[11px] font-mono bg-card/80"
              inputMode="numeric"
              aria-label={unit === 'tokens' ? '最大 token 过滤' : '最大长度过滤'}
            />
            {(minLen > 0 || maxLen > 0) ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-[11px]"
                onClick={() => {
                  setMinLen(0)
                  setMaxLen(0)
                }}
              >
                清除
              </Button>
            ) : null}
          </div>
          {selectedChunkIndex != null ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setSelectedChunkIndex(null)}
            >
              清除锁定
            </Button>
          ) : null}
          {matchesLabel ? <span className="text-[10px] text-muted-foreground font-mono">{matchesLabel}</span> : null}
          <div className="hidden lg:flex items-center gap-2 text-[10px] text-muted-foreground">
            <MousePointer2 className="w-3 h-3" />
            {showOriginalPanel
              ? '悬停定位 · 点击锁定 · ↑↓/J K 导航 · / 搜索'
              : '点击锁定 · ↑↓/J K 导航（原文已隐藏） · / 搜索'}
            <CornerDownLeft className="w-3 h-3 opacity-70" />
            Esc 取消 · G 首尾
          </div>
        </div>
      </div>

      {selectedChunk ? (
        <div className="border-b border-border/60 bg-card/70 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono font-medium text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                  #{selectedChunkIndex != null ? selectedChunkIndex + 1 : '-'}
                </span>
                {selectedChunk.page_number != null ? (
                  <span className="text-xs text-muted-foreground">P.{selectedChunk.page_number}</span>
                ) : null}
                <span className="text-[10px] text-muted-foreground font-mono">
                  {selectedChunk.start_index}-{selectedChunk.end_index} · {selectedChunkLenLabel}
                </span>
              </div>
              <div className="mt-1 text-[11px] text-muted-foreground line-clamp-2">
                {(selectedChunk.content || '').slice(0, 260)}
                {(selectedChunk.content || '').length > 260 ? '…' : ''}
              </div>
            </div>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => void copyText(selectedChunk.content || '', '已复制切片内容')}
                aria-label="复制切片内容"
                title="复制切片内容"
              >
                <Copy className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => void copyText(JSON.stringify(selectedChunk, null, 2), '已复制切片 JSON')}
                aria-label="复制切片 JSON"
                title="复制切片 JSON"
              >
                <Braces className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => {
                  const name = (previewData?.filename || '').trim() || 'document'
                  const pageLabel = selectedChunk.page_number != null ? ` · P.${selectedChunk.page_number}` : ''
                  const tok = typeof selectedChunk.tokens_est === 'number' ? ` · ${selectedChunk.tokens_est} tok` : ''
                  const fence = '````'
                  const raw = String(selectedChunk.content || '').trim()
                  const excerpt = raw.length > 2000 ? `${raw.slice(0, 2000)}…` : raw
                  const text = [
                    `【${name} · chunk #${(selectedChunkIndex ?? 0) + 1}${pageLabel}${tok} · ${selectedChunk.start_index}-${selectedChunk.end_index}】`,
                    `${fence}text`,
                    excerpt,
                    fence,
                  ].join('\n')
                  void copyText(text, '已复制引用')
                }}
                aria-label="复制引用"
                title="复制引用"
              >
                <Quote className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() =>
                  void copyText(
                    '```text\n' + (selectedChunk.content || '') + '\n```\n',
                    '已复制 Markdown 代码块'
                  )
                }
                aria-label="复制为 Markdown 代码块"
                title="复制为 Markdown 代码块"
              >
                <Code2 className="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 px-3 text-[11px]"
                onClick={() => setSelectedChunkIndex(null)}
              >
                取消锁定
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <div
        ref={scrollRef}
        tabIndex={0}
        onKeyDown={(e) => {
          if (!previewData?.chunks?.length) return
          if (isEditableTarget(e.target)) return
          if (filteredChunks.length === 0) return

          const currentPos =
            selectedChunkIndex == null
              ? -1
              : filteredChunks.findIndex((item) => item.index === selectedChunkIndex)

          const clamp = (n: number) => Math.max(0, Math.min(filteredChunks.length - 1, n))

          if (e.key === '/') {
            e.preventDefault()
            searchRef.current?.focus()
            return
          }
          if (e.key === 'Home' || (e.key.toLowerCase() === 'g' && !e.shiftKey)) {
            e.preventDefault()
            setSelectedChunkIndex(filteredChunks[0]?.index ?? null)
            return
          }
          if (e.key === 'End' || (e.key.toLowerCase() === 'g' && e.shiftKey)) {
            e.preventDefault()
            setSelectedChunkIndex(filteredChunks[filteredChunks.length - 1]?.index ?? null)
            return
          }

          if (e.key === 'ArrowDown' || e.key.toLowerCase() === 'j') {
            e.preventDefault()
            const nextPos = clamp(currentPos < 0 ? 0 : currentPos + 1)
            setSelectedChunkIndex(filteredChunks[nextPos]?.index ?? null)
            return
          }
          if (e.key === 'ArrowUp' || e.key.toLowerCase() === 'k') {
            e.preventDefault()
            const nextPos = clamp(currentPos < 0 ? 0 : currentPos - 1)
            setSelectedChunkIndex(filteredChunks[nextPos]?.index ?? null)
            return
          }
          if (e.key === 'Escape') {
            e.preventDefault()
            setSelectedChunkIndex(null)
            return
          }
        }}
        className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-4 focus-ring"
        aria-label="切片列表（可键盘导航）"
      >
        <div
          className="min-h-full rounded-2xl border border-border/60 bg-card/70 p-3 shadow-sm backdrop-blur ring-1 ring-border/40"
          style={{
            height: showVirtualized ? `${rowVirtualizer.getTotalSize()}px` : undefined,
            position: showVirtualized ? 'relative' : undefined,
          }}
        >
          {previewData?.chunks ? (
            filteredChunks.length > 0 ? (
              rowVirtualizer.getVirtualItems().map((virtualRow) => {
                const item = filteredChunks[virtualRow.index]
                if (!item) return null
                const { chunk, index } = item
                const isHovered = hoveredChunkIndex === index
                const isSelected = selectedChunkIndex === index

                return (
                  <div
                    key={virtualRow.key}
                    data-index={virtualRow.index}
                    ref={rowVirtualizer.measureElement}
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      transform: `translateY(${virtualRow.start}px)`,
                    }}
                    className="pb-3"
                  >
                    <ChunkCard
                      chunk={chunk}
                      index={index}
                      unit={unit}
                      sourceFilename={previewData?.filename}
                      isHovered={isHovered}
                      isSelected={isSelected}
                      query={query}
                      onMouseEnter={() => setHoveredChunkIndex(index)}
                      onMouseLeave={() => setHoveredChunkIndex(null)}
                      onToggleSelect={() => {
                        setSelectedChunkIndex(selectedChunkIndex === index ? null : index)
                        scrollRef.current?.focus()
                      }}
                    />
                  </div>
                )
              })
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
                <Search className="w-10 h-10 opacity-20" />
                <p className="text-xs text-muted-foreground">未找到匹配切片</p>
              </div>
            )
          ) : isLoading ? (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
              <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none opacity-20" />
              <p className="text-xs">生成中...</p>
            </div>
          ) : error ? (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
              <AlertCircle className="w-10 h-10 opacity-20" />
              <p className="text-xs text-muted-foreground">生成预览失败</p>
              <p className="text-[10px] text-muted-foreground max-w-xs text-center">{error}</p>
              <Button variant="outline" size="sm" className="mt-2 h-8 px-3 text-[11px]" onClick={() => runPreview()}>
                重试
              </Button>
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
              <Layers className="w-12 h-12 opacity-10" />
              <p className="text-xs">等待生成预览</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
