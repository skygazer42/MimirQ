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
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>入库管线配置</DialogTitle>
          <DialogDescription>仅影响新上传/新导入文档，可随时调整</DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground/80">解析方式</div>
            <ParserDropdown value={parserBackend} onChange={setParserBackend} />
          </div>
          <div className="space-y-2">
            <div className="text-sm font-medium text-foreground/80">切块策略</div>
            <ChunkStrategyDropdown value={chunkStrategy} onChange={setChunkStrategy} />
          </div>
        </div>

        <PipelineOptionsPanel />
      </DialogContent>
    </Dialog>
  )
}
