'use client'

import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { ChunkStrategyDropdown } from '@/components/business/chunk-strategy-dropdown'
import { Panel } from '@/components/ui/panel'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { Sliders } from 'lucide-react'

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
      <div className="mb-6 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <Sliders className="h-5 w-5 text-primary" />
          前端偏好（本地）
        </h2>
        <div className="flex items-center gap-2 rounded-full border border-border bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
          <span>仅保存在浏览器，影响新上传/预览</span>
        </div>
      </div>

      <Panel className="space-y-6" padding="lg">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground/80">解析方式</div>
            <ParserDropdown value={parserBackend} onChange={setParserBackend} />
          </div>
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground/80">切块策略</div>
            <ChunkStrategyDropdown value={chunkStrategy} onChange={setChunkStrategy} />
          </div>
        </div>

        <div>
          <div className="mb-3 text-sm font-medium text-foreground/80">入库管线</div>
          <PipelineOptionsPanel />
        </div>
      </Panel>
    </section>
  )
}
