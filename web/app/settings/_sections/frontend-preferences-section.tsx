'use client'

import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { ChunkStrategyDropdown } from '@/components/business/chunk-strategy-dropdown'
import { Panel } from '@/components/ui/panel'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { ChevronDown, Sliders } from 'lucide-react'

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
      <div className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-[-0.02em] text-slate-950">
          <Sliders className="h-4 w-4 text-blue-600" />
          前端偏好（本地）
        </h2>
        <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-medium text-slate-500">
          <span>仅保存在浏览器，影响新上传/预览</span>
        </div>
      </div>

      <Panel className="space-y-5 rounded-[22px] border-slate-200/80 bg-white/92 shadow-[0_18px_44px_rgba(15,23,42,0.06)]" padding="lg">
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <div className="space-y-2">
            <div className="text-[13px] font-semibold text-slate-700">解析方式</div>
            <ParserDropdown value={parserBackend} onChange={setParserBackend} />
          </div>
          <div className="space-y-2">
            <div className="text-[13px] font-semibold text-slate-700">切块策略</div>
            <ChunkStrategyDropdown value={chunkStrategy} onChange={setChunkStrategy} />
          </div>
        </div>

        <details className="group rounded-2xl border border-slate-200 bg-slate-50/45">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-[13px] font-semibold text-slate-700 transition-colors hover:bg-slate-50">
            <span>入库管线高级配置</span>
            <ChevronDown className="size-4 text-slate-400 transition-transform group-open:rotate-180" />
          </summary>
          <div className="border-t border-slate-200 bg-white/75 p-3">
            <PipelineOptionsPanel compact />
          </div>
        </details>
      </Panel>
    </section>
  )
}
