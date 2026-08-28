'use client'

import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { ChunkStrategyDropdown } from '@/components/business/chunk-strategy-dropdown'
import { Panel } from '@/components/ui/panel'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { ChevronDown, HelpCircle } from 'lucide-react'

type FrontendPreferencesSectionProps = {
  parserBackend: string
  setParserBackend: (value: string) => void
  chunkStrategy: string
  setChunkStrategy: (value: string) => void
}

export function FrontendPreferencesSection({
  parserBackend,
  setParserBackend,
  chunkStrategy,
  setChunkStrategy,
}: Readonly<FrontendPreferencesSectionProps>) {
  return (
    <section>
      <Panel
        className="space-y-3 rounded-xl border-info/15 bg-info/[0.025] shadow-none"
        padding="md"
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-[12px] font-medium text-foreground/78">
              <span>解析方式</span>
              <span className="group/frontend-local-help relative inline-flex">
                <button
                  type="button"
                  aria-label="查看前端偏好保存说明"
                  className="inline-flex size-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-info/10 hover:text-info focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-info/25"
                >
                  <HelpCircle className="h-3.5 w-3.5" />
                </button>
                <span className="pointer-events-none absolute left-1/2 top-full z-30 mt-2 hidden w-[min(320px,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border border-info/20 bg-popover px-3 py-2 text-[11px] font-medium leading-relaxed text-popover-foreground shadow-[0_14px_34px_hsl(var(--foreground)/0.14)] group-hover/frontend-local-help:block group-focus-within/frontend-local-help:block md:left-full md:top-1/2 md:mt-0 md:ml-2 md:-translate-x-0 md:-translate-y-1/2">
                  这些偏好仅保存在当前浏览器，用于新上传和预览流程，不会写入后端配置
                </span>
              </span>
            </div>
            <ParserDropdown
              value={parserBackend}
              onChange={setParserBackend}
              surface="ocean"
            />
          </div>
          <div className="space-y-2">
            <div className="text-[12px] font-medium text-foreground/78">
              切块策略
            </div>
            <ChunkStrategyDropdown
              value={chunkStrategy}
              onChange={setChunkStrategy}
              surface="ocean"
            />
          </div>
        </div>

        <details className="group rounded-[14px] border border-border/60 bg-muted/24">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-[12px] font-medium text-foreground/78 transition-colors hover:bg-muted/35">
            <span>入库管线高级配置</span>
            <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-180" />
          </summary>
          <div className="border-t border-border/60 bg-info/[0.025] p-3">
            <PipelineOptionsPanel compact />
          </div>
        </details>
      </Panel>
    </section>
  )
}
