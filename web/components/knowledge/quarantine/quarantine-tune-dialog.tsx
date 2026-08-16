'use client'

import { RotateCcw, Settings2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import type { Document, DocumentPipelineOptions } from '@/types'

import type { ActingState } from '@/app/knowledge/quarantine/types'

function finiteNumberOrUndefined(value: string): number | undefined {
  if (value === '') return undefined
  const numericValue = Number(value)
  return Number.isFinite(numericValue) ? numericValue : undefined
}

type QuarantineTuneDialogProps = {
  acting: ActingState
  open: boolean
  patch: DocumentPipelineOptions
  target: Document | null
  onApplyDisableQualityFilters: () => void
  onOpenChange: (open: boolean) => void
  onPatchChange: (nextPatch: DocumentPipelineOptions) => void
  onResetRecommended: () => void
  onSave: (options: { retryAfterSave: boolean }) => void
}

export function QuarantineTuneDialog({
  acting,
  open,
  patch,
  target,
  onApplyDisableQualityFilters,
  onOpenChange,
  onPatchChange,
  onResetRecommended,
  onSave,
}: Readonly<QuarantineTuneDialogProps>) {
  const tuneBusy = acting?.action === 'tune'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[720px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Settings2 className="size-5 text-warning" />
            调参回放
          </DialogTitle>
          <DialogDescription>
            仅修改该文档的 pipeline overrides（`metadata.pipeline`），用于快速回放重试；不会影响其他文档。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          <div className="rounded-xl border border-border bg-muted/40 p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-medium text-foreground">
                  推荐预设
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  关闭对应质量过滤器，让更多内容进入切块（仍建议人工抽检）。
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="rounded-xl"
                  onClick={onApplyDisableQualityFilters}
                >
                  关闭质量过滤
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="rounded-xl"
                  onClick={onResetRecommended}
                  disabled={!target}
                >
                  还原推荐
                </Button>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-3 rounded-xl border border-border bg-card/60 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium">大纲过滤</div>
                  <div className="text-xs text-muted-foreground">
                    outline_only
                  </div>
                </div>
                <Switch
                  checked={Boolean(patch.governance_drop_outline_only)}
                  onCheckedChange={(value) =>
                    onPatchChange({
                      ...patch,
                      governance_drop_outline_only: value,
                    })
                  }
                  className="data-[state=checked]:bg-warning"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">
                    最小内容字符
                  </Label>
                  <Input
                    type="number"
                    min={0}
                    max={200000}
                    value={
                      typeof patch.governance_drop_outline_min_content_chars ===
                      'number'
                        ? patch.governance_drop_outline_min_content_chars
                        : ''
                    }
                    onChange={(event) => {
                      const value = finiteNumberOrUndefined(event.target.value)
                      onPatchChange({
                        ...patch,
                        governance_drop_outline_min_content_chars: value,
                      })
                    }}
                    className="h-9 rounded-lg"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">
                    标题占比阈值
                  </Label>
                  <Input
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={
                      typeof patch.governance_drop_outline_max_heading_ratio ===
                      'number'
                        ? patch.governance_drop_outline_max_heading_ratio
                        : ''
                    }
                    onChange={(event) => {
                      const value = finiteNumberOrUndefined(event.target.value)
                      onPatchChange({
                        ...patch,
                        governance_drop_outline_max_heading_ratio: value,
                      })
                    }}
                    className="h-9 rounded-lg"
                  />
                </div>
              </div>
            </div>

            <div className="space-y-3 rounded-xl border border-border bg-card/60 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium">低密度过滤</div>
                  <div className="text-xs text-muted-foreground">
                    low_density
                  </div>
                </div>
                <Switch
                  checked={Boolean(patch.governance_drop_low_density)}
                  onCheckedChange={(value) =>
                    onPatchChange({
                      ...patch,
                      governance_drop_low_density: value,
                    })
                  }
                  className="data-[state=checked]:bg-warning"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">
                  密度阈值
                </Label>
                <Input
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  value={
                    typeof patch.governance_drop_low_density_threshold ===
                    'number'
                      ? patch.governance_drop_low_density_threshold
                      : ''
                  }
                  onChange={(event) => {
                    const value = finiteNumberOrUndefined(event.target.value)
                    onPatchChange({
                      ...patch,
                      governance_drop_low_density_threshold: value,
                    })
                  }}
                  className="h-9 rounded-lg"
                />
              </div>
            </div>
          </div>

          <div className="space-y-3 rounded-xl border border-border bg-card/60 p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium">隔离策略</div>
                <div className="text-xs text-muted-foreground">
                  quarantine_on_drop
                </div>
              </div>
              <Switch
                checked={Boolean(patch.governance_quarantine_on_drop)}
                onCheckedChange={(value) =>
                  onPatchChange({
                    ...patch,
                    governance_quarantine_on_drop: value,
                  })
                }
                className="data-[state=checked]:bg-primary"
              />
            </div>
            <div className="text-xs text-muted-foreground">
              开启后：触发质量过滤时标记为 quarantined（而非 failed），便于人工复核。
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-2">
          <Button
            type="button"
            variant="outline"
            className="rounded-xl"
            onClick={() => onOpenChange(false)}
            disabled={tuneBusy}
          >
            取消
          </Button>
          <Button
            type="button"
            variant="outline"
            className="rounded-xl"
            onClick={() => onSave({ retryAfterSave: false })}
            disabled={tuneBusy}
          >
            <Settings2
              className={cn(
                'size-4 mr-1',
                tuneBusy ? 'animate-spin motion-reduce:animate-none' : ''
              )}
            />
            保存配置
          </Button>
          <Button
            type="button"
            variant="warning"
            className="rounded-xl"
            onClick={() => onSave({ retryAfterSave: true })}
            disabled={tuneBusy}
          >
            <RotateCcw
              className={cn(
                'size-4 mr-1',
                tuneBusy ? 'animate-spin motion-reduce:animate-none' : ''
              )}
            />
            保存并重试
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
