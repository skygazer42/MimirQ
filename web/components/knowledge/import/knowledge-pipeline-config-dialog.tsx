'use client'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
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
      <DialogContent className="flex max-h-[min(88dvh,820px)] w-[calc(100%_-_2rem)] max-w-2xl flex-col gap-0 overflow-hidden rounded-xl p-0">
        <DialogHeader className="shrink-0 border-b border-border/75 bg-popover px-6 pt-6 pb-4 text-left">
          <DialogTitle>入库管线配置</DialogTitle>
          <DialogDescription>仅对新导入文档生效。</DialogDescription>
        </DialogHeader>

        <div
          data-knowledge-dialog-body="true"
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain custom-scrollbar px-6 py-5"
        >
          <fieldset className="m-0 min-w-0 border-0 p-0 space-y-5">
            <legend className="sr-only">入库管线配置</legend>
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
          </fieldset>
        </div>
        <DialogFooter className="shrink-0 gap-2 border-t border-border/75 bg-popover px-6 py-4 sm:space-x-0">
          <Button type="button" onClick={() => onOpenChange(false)}>
            完成
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
