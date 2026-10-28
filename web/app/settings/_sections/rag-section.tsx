'use client'

import type { ReactNode } from 'react'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { SettingsSwitch } from '@/components/settings/settings-switch'
import type { SystemSettings } from '@/lib/api'
import { RERANKER_PROVIDER_OPTIONS } from '@/lib/reranker-provider-options'
import { HelpCircle } from '@/components/icons'
import { cn } from '@/lib/utils'
import { settingsTextTokens } from '@/components/ui/system-page-tokens'

type RagSettings = NonNullable<SystemSettings['rag']>

type RagSectionProps = {
  rag: RagSettings
  updateRag: (patch: Partial<RagSettings>) => void
}

const RANGE_INPUT_CLASS =
  'h-2 w-full cursor-pointer appearance-none rounded-full bg-muted/40 accent-[hsl(var(--primary))] outline-none transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring/30 focus-visible:ring-offset-2 [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-background [&::-moz-range-thumb]:bg-primary [&::-moz-range-track]:h-2 [&::-moz-range-track]:rounded-full [&::-moz-range-track]:bg-muted/40 [&::-webkit-slider-runnable-track]:h-2 [&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-runnable-track]:bg-muted/40 [&::-webkit-slider-thumb]:mt-[-4px] [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-background [&::-webkit-slider-thumb]:bg-primary'
const DEFAULT_RERANKER_PROVIDER = 'llm'

function InlineHelp({
  label,
  children,
}: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <span className="group/help relative inline-flex align-middle">
      <button
        type="button"
        aria-label={label}
        className="ml-1 inline-flex size-4 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
      >
        <HelpCircle className="size-3.5" />
      </button>
      <span className="pointer-events-none absolute left-1/2 top-full z-30 mt-2 hidden w-64 -translate-x-1/2 rounded-xl border border-border/60 bg-popover px-3 py-2 text-[13px] font-medium leading-relaxed text-popover-foreground shadow-[0_12px_30px_hsl(var(--foreground)/0.12)] group-hover/help:block group-focus-within/help:block">
        {children}
      </span>
    </span>
  )
}

export function RagSection({ rag, updateRag }: Readonly<RagSectionProps>) {
  const isBm25IndexEnabled = rag.bm25_index_enabled
  const isRerankerEnabled = rag.enable_reranker
  const showImageInAnswer = rag.show_image_in_answer
  const rerankerProviderValue = rag.reranker_provider || DEFAULT_RERANKER_PROVIDER

  return (
    <section className="space-y-5">
      <div className="space-y-4">
        <h3 className={settingsTextTokens.panelTitle}>检索召回</h3>
        <div className="grid gap-5 md:grid-cols-2">
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div
                className={cn(
                  settingsTextTokens.fieldLabel,
                  'text-foreground/80'
                )}
              >
                召回 Top K
              </div>
              <span className="text-[13px] tabular-nums text-foreground">
                {rag.retrieval_top_k}
              </span>
            </div>
            <input
              type="range"
              aria-label="召回 Top K"
              min="1"
              max="20"
              value={rag.retrieval_top_k}
              onChange={(event) =>
                updateRag({
                  retrieval_top_k: Number.parseInt(event.target.value, 10),
                })
              }
              className={RANGE_INPUT_CLASS}
            />
            <p className="mt-1.5 text-[13px] text-muted-foreground">
              每次检索返回的最相关文档片段数量
            </p>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div
                className={cn(
                  settingsTextTokens.fieldLabel,
                  'text-foreground/80'
                )}
              >
                相似度阈值
              </div>
              <span className="text-[13px] tabular-nums text-foreground">
                {rag.similarity_threshold.toFixed(1)}
              </span>
            </div>
            <input
              type="range"
              aria-label="相似度阈值"
              min="0"
              max="1"
              step="0.1"
              value={rag.similarity_threshold}
              onChange={(event) =>
                updateRag({
                  similarity_threshold: Number.parseFloat(event.target.value),
                })
              }
              className={RANGE_INPUT_CLASS}
            />
            <p className="mt-1.5 text-[13px] text-muted-foreground">
              过滤掉相关性得分低于此值的片段
            </p>
          </div>

        </div>
          <div>
            <div className="flex items-start justify-between gap-4">
              <div>
                <div
                  className={cn(settingsTextTokens.fieldLabel, 'text-foreground')}
                >
                  BM25 关键字检索
                </div>
                <div className="mt-1 text-[13px] text-muted-foreground">
                  启用关键词通道，对精确词匹配召回更友好
                  <InlineHelp label="BM25 检索模式说明">
                    这里对应 hybrid / keyword 模式；适合标题、术语、编号和精确关键词匹配
                  </InlineHelp>
                </div>
              </div>
              <SettingsSwitch
                aria-label="切换 BM25 检索"
                checked={isBm25IndexEnabled}
                onCheckedChange={(checked) =>
                  updateRag({ bm25_index_enabled: checked })
                }
              />
            </div>
            <p className="mt-2 text-[13px] text-muted-foreground">
              关闭后将不会使用或构建 BM25 索引
              <InlineHelp label="关闭 BM25 的影响">
                更省内存和 CPU，但可能降低关键词类问题的召回质量
              </InlineHelp>
            </p>
          </div>

      </div>

      <div className="space-y-4 border-t border-border/60 pt-5">
          <div>
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className={settingsTextTokens.panelTitle}>
                  启用重排序
                  <InlineHelp label="Reranker 说明">
                    Reranker 会对候选片段二次排序，适合提升复杂问题的答案质量
                  </InlineHelp>
                </h3>
                <div className="mt-1 text-[13px] text-muted-foreground">
                  用重排序模型对候选片段二次排序
                  <InlineHelp label="重排序成本说明">
                    通常可提升答案质量，但会增加检索链路延迟和模型调用成本
                  </InlineHelp>
                </div>
              </div>
              <SettingsSwitch
                aria-label="切换重排器"
                checked={isRerankerEnabled}
                onCheckedChange={(checked) =>
                  updateRag({ enable_reranker: checked })
                }
              />
            </div>
            <p className="mt-2 text-[13px] text-muted-foreground">
              开启后会使用下方重排服务与数量，并同步到实验页面作为默认值
            </p>
          </div>

        <div className="grid gap-5 md:grid-cols-2">
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div
                className={cn(
                  settingsTextTokens.fieldLabel,
                  'text-foreground/80'
                )}
              >
                重排服务
              </div>
            </div>
            <Select
              value={rerankerProviderValue}
              onValueChange={(value) => updateRag({ reranker_provider: value })}
            >
              <SelectTrigger aria-label="重排服务" className="h-11 sm:h-9 rounded-md border-input bg-background text-[13px]">
                <SelectValue placeholder="选择重排服务" />
              </SelectTrigger>
              <SelectContent>
                {RERANKER_PROVIDER_OPTIONS.map((option) => (
                  <SelectItem key={option.key} value={option.key}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="mt-1.5 text-[13px] text-muted-foreground">
              用作默认重排服务，实验页可临时覆盖
              <InlineHelp label="重排服务后端字段">
                对应后端 RERANKER_PROVIDER；主界面只显示中文服务名称
              </InlineHelp>
            </p>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div
                className={cn(
                  settingsTextTokens.fieldLabel,
                  'text-foreground/80'
                )}
              >
                重排数量
              </div>
            </div>
            <Input
              type="number"
              aria-label="重排数量"
              min={1}
              max={200}
              value={rag.reranker_top_n}
              onChange={(event) =>
                updateRag({
                  reranker_top_n: Math.max(
                    1,
                    Math.min(200, Number.parseInt(event.target.value || '1', 10))
                  ),
                })
              }
              className="h-11 sm:h-9 rounded-md border-input bg-background text-[13px]"
            />
            <p className="mt-1.5 text-[13px] text-muted-foreground">
              用作默认重排数量，建议保持 10-50
              <InlineHelp label="重排数量后端字段">
                对应后端 RERANKER_TOP_N
              </InlineHelp>
            </p>
          </div>

        </div>
      </div>

      <div className="space-y-4 border-t border-border/60 pt-5">
        <h3 className={settingsTextTokens.panelTitle}>内容切分</h3>
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div
                className={cn(
                  settingsTextTokens.fieldLabel,
                  'text-foreground/80'
                )}
              >
                分块大小
              </div>
              <span className="text-[13px] tabular-nums text-foreground">
                {rag.chunk_size}
              </span>
            </div>
            <input
              type="range"
              min="200"
              aria-label="分块大小"
              max="4000"
              step="100"
              value={rag.chunk_size}
              onChange={(event) =>
                updateRag({
                  chunk_size: Number.parseInt(event.target.value, 10),
                })
              }
              className={RANGE_INPUT_CLASS}
            />
            <p className="mt-1.5 text-[13px] text-muted-foreground">
              文档分块的目标字符数
            </p>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div
                className={cn(
                  settingsTextTokens.fieldLabel,
                  'text-foreground/80'
                )}
              >
                分块重叠
              </div>
              <span className="text-[13px] tabular-nums text-foreground">
                {rag.chunk_overlap}
              </span>
            </div>
            <input
              type="range"
              min="0"
              max="1000"
              aria-label="分块重叠"
              step="50"
              value={rag.chunk_overlap}
              onChange={(event) =>
                updateRag({
                  chunk_overlap: Number.parseInt(event.target.value, 10),
                })
              }
              className={RANGE_INPUT_CLASS}
            />
            <p className="mt-1.5 text-[13px] text-muted-foreground">
              相邻分块的重叠字符数
              <InlineHelp label="分块重叠说明">
                chunk 是写入索引的文本片段；增加重叠可提高上下文连续性，但会增加索引体积
              </InlineHelp>
            </p>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <div
                className={cn(
                  settingsTextTokens.fieldLabel,
                  'text-foreground/80'
                )}
              >
                最小分块长度
              </div>
            </div>
            <Input
              type="number"
              min={0}
              max={5000}
              aria-label="最小分块长度"
              className="h-11 rounded-md border-input bg-background text-[13px] sm:h-9"
              value={rag.chunk_min_chars}
              onChange={(event) =>
                updateRag({
                  chunk_min_chars: Math.max(
                    0,
                    Number.parseInt(event.target.value || '0', 10)
                  ),
                })
              }
            />
            <p className="mt-1.5 text-[13px] text-muted-foreground">
              入库时丢弃过短分块
              <InlineHelp label="最小分块长度说明">
                0 表示关闭；图片和表格分块会尽量保留，避免误删结构化内容
              </InlineHelp>
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-4 border-t border-border/60 pt-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className={settingsTextTokens.panelTitle}>
              回答附图
              <InlineHelp label="回答附图说明">
                召回结果命中图片证据时，在答案末尾附上图片引用，便于核对图表、截图和版面证据。
              </InlineHelp>
            </h3>
            <p className={cn(settingsTextTokens.helpText, 'mt-1')}>
              只影响回答展示，不改变解析、切块或向量索引。
            </p>
          </div>
          <SettingsSwitch
            aria-label="切换回答附图"
            checked={showImageInAnswer}
            onCheckedChange={(checked) => updateRag({ show_image_in_answer: checked })}
          />
        </div>
        <div className="flex items-center gap-3">
          <label htmlFor="rag-image-max" className={cn(settingsTextTokens.fieldLabel, 'shrink-0')}>最多附图</label>
          <Input
            id="rag-image-max"
            type="number"
            min={0}
            max={10}
            value={rag.image_append_max}
            disabled={!showImageInAnswer}
            onChange={(event) => updateRag({ image_append_max: Math.max(0, Math.min(10, Number.parseInt(event.target.value || '0', 10))) })}
            className="h-11 w-24 border-input bg-background text-[13px] disabled:opacity-60 sm:h-9"
          />
        </div>
      </div>
    </section>
  )
}
