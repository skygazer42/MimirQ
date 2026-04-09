'use client'

import { Input } from '@/components/ui/input'
import type { SystemSettings } from '@/lib/api'
import { Sliders, ToggleLeft, ToggleRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { systemPageTokens } from '@/components/ui/system-page-tokens'

type RagSettings = NonNullable<SystemSettings['rag']>

type RagSectionProps = {
  rag: RagSettings
  updateRag: (patch: Partial<RagSettings>) => void
}

export function RagSection({ rag, updateRag }: Readonly<RagSectionProps>) {
  const isBm25IndexEnabled = rag.bm25_index_enabled
  const isRerankerEnabled = rag.enable_reranker

  return (
    <section>
      <h2 className={cn('mb-4 flex items-center gap-2 text-base', systemPageTokens.heading)}>
        <Sliders className="h-4 w-4 text-primary" />
        检索增强生成参数（RAG）
      </h2>

      <div className="rounded-lg border border-border/70 bg-card p-4 shadow-none">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div className={cn(systemPageTokens.microLabel, 'text-foreground/80')}>召回 Top K</div>
              <span className="rounded bg-muted px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                {rag.retrieval_top_k}
              </span>
            </div>
            <input
              type="range"
              min="1"
              max="20"
              value={rag.retrieval_top_k}
              onChange={(event) =>
                updateRag({ retrieval_top_k: Number.parseInt(event.target.value, 10) })
              }
              className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-muted accent-primary"
            />
            <p className="mt-1.5 text-[11px] text-muted-foreground">每次检索返回的最相关文档片段数量</p>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div className={cn(systemPageTokens.microLabel, 'text-foreground/80')}>相似度阈值</div>
              <span className="rounded bg-muted px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                {rag.similarity_threshold.toFixed(1)}
              </span>
            </div>
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={rag.similarity_threshold}
              onChange={(event) =>
                updateRag({ similarity_threshold: Number.parseFloat(event.target.value) })
              }
              className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-muted accent-primary"
            />
            <p className="mt-1.5 text-[11px] text-muted-foreground">过滤掉相关性得分低于此值的片段</p>
          </div>

          <div className="rounded-lg border border-border bg-muted/30 p-3">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className={cn(systemPageTokens.microLabel, 'text-foreground')}>BM25 关键字检索</div>
                <div className="mt-1 text-[11px] text-muted-foreground">
                  启用关键词通道（hybrid/keyword 模式），对“精确词匹配”召回更友好
                </div>
              </div>
              <button
                type="button"
                onClick={() => updateRag({ bm25_index_enabled: !isBm25IndexEnabled })}
                className="shrink-0"
                aria-label="切换 BM25 检索"
              >
                {isBm25IndexEnabled ? (
                  <ToggleRight className="h-9 w-9 text-primary" />
                ) : (
                  <ToggleLeft className="h-9 w-9 text-muted-foreground hover:text-muted-foreground" />
                )}
              </button>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              关闭后将不会使用/构建 BM25 索引（更省内存/CPU，但可能降低召回）
            </p>
          </div>

          <div className="rounded-lg border border-border bg-muted/30 p-3">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className={cn(systemPageTokens.microLabel, 'text-foreground')}>启用重排序（Reranker）</div>
                <div className="mt-1 text-[11px] text-muted-foreground">
                  用重排序模型对候选片段二次排序，通常可提升答案质量（会增加延迟/成本）
                </div>
              </div>
              <button
                type="button"
                onClick={() => updateRag({ enable_reranker: !isRerankerEnabled })}
                className="shrink-0"
                aria-label="切换重排器"
              >
                {isRerankerEnabled ? (
                  <ToggleRight className="h-9 w-9 text-primary" />
                ) : (
                  <ToggleLeft className="h-9 w-9 text-muted-foreground hover:text-muted-foreground" />
                )}
              </button>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              需要先在“重排序模型”里配置 Provider（否则可能无效果）
            </p>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div className={cn(systemPageTokens.microLabel, 'text-foreground/80')}>分块大小</div>
              <span className="rounded bg-muted px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                {rag.chunk_size}
              </span>
            </div>
            <input
              type="range"
              min="200"
              max="4000"
              step="100"
              value={rag.chunk_size}
              onChange={(event) => updateRag({ chunk_size: Number.parseInt(event.target.value, 10) })}
              className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-muted accent-primary"
            />
            <p className="mt-1.5 text-[11px] text-muted-foreground">文档分块的目标字符数</p>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div className={cn(systemPageTokens.microLabel, 'text-foreground/80')}>分块重叠</div>
              <span className="rounded bg-muted px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                {rag.chunk_overlap}
              </span>
            </div>
            <input
              type="range"
              min="0"
              max="1000"
              step="50"
              value={rag.chunk_overlap}
              onChange={(event) =>
                updateRag({ chunk_overlap: Number.parseInt(event.target.value, 10) })
              }
              className="h-1.5 w-full cursor-pointer appearance-none rounded-lg bg-muted accent-primary"
            />
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              相邻分块（chunk）的重叠字符数（提高连续性，但会增加索引体积）
            </p>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div className={cn(systemPageTokens.microLabel, 'text-foreground/80')}>最小分块长度</div>
              <span className="rounded bg-muted px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                {rag.chunk_min_chars}
              </span>
            </div>
            <Input
              type="number"
              min={0}
              max={5000}
              value={rag.chunk_min_chars}
              onChange={(event) =>
                updateRag({
                  chunk_min_chars: Math.max(0, Number.parseInt(event.target.value || '0', 10)),
                })
              }
            />
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              入库时丢弃过短分块（chunk）（0 表示关闭；图片/表格分块会尽量保留）
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}
