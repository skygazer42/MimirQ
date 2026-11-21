'use client'

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ChunkStrategyDropdown } from '@/components/business/chunk-strategy-dropdown'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'

type KnowledgePipelineConfigDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function KnowledgePipelineConfigDialog({ open, onOpenChange }: Readonly<KnowledgePipelineConfigDialogProps>) {
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] max-w-2xl overflow-y-auto overscroll-contain">
        <DialogHeader>
          <DialogTitle>入库管线配置</DialogTitle>
          <DialogDescription>仅影响新上传/新导入文档，可随时调整</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 md:grid-cols-2">
          <fieldset className="min-w-0">
            <legend className="mb-2 text-sm font-medium text-foreground/80">解析方式</legend>
            <ParserDropdown value={parserBackend} onChange={setParserBackend} />
          </fieldset>
          <fieldset className="min-w-0">
            <legend className="mb-2 text-sm font-medium text-foreground/80">切块策略</legend>
            <ChunkStrategyDropdown value={chunkStrategy} onChange={setChunkStrategy} />
          </fieldset>
        </div>

        <PipelineOptionsPanel />
      </DialogContent>
    </Dialog>
  )
}
