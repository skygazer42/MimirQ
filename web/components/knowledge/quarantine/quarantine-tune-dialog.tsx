'use client'

import { useId } from 'react'
import { RotateCcw, Settings2 } from '@/components/icons'

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
import type { Document, DocumentPipelineOptions } from '@/types'

import type { ActingState } from '@/app/knowledge/quarantine/types'

function readNumberOverride(input: HTMLInputElement): number | null {
  return input.value === '' ? null : input.valueAsNumber
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
  const fieldId = useId()
  const tuneBusy = acting !== null && acting.id === target?.id
  const tuneDisabled = target === null || tuneBusy

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (nextOpen || !tuneBusy) onOpenChange(nextOpen)
      }}
    >
      <DialogContent className="sm:max-w-[720px]" showCloseButton={!tuneBusy}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Settings2 className="size-5 text-warning" />
            调参回放
          </DialogTitle>
          <DialogDescription>
            仅修改该文档的 pipeline overrides（`metadata.pipeline`），用于快速回放重试；不会影响其他文档。
          </DialogDescription>
        </DialogHeader>

        <form
          id={fieldId}
          onSubmit={(event) => {
            event.preventDefault()
            if (tuneDisabled) return
            const submitter = (event.nativeEvent as SubmitEvent).submitter
            onSave({ retryAfterSave: submitter instanceof HTMLButtonElement && submitter.value === 'retry' })
          }}
        >
          <fieldset disabled={tuneDisabled} className="min-w-0 space-y-5">
            <legend className="sr-only">文档处理配置</legend>
            <div className="rounded-xl border border-border bg-muted/40 p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-medium text-foreground">推荐预设</div>
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
                  <Button type="button" size="sm" variant="outline" className="rounded-xl" onClick={onResetRecommended}>
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
                    <div className="text-xs text-muted-foreground">outline_only</div>
                  </div>
                  <Switch
                    aria-label="大纲过滤"
                    checked={patch.governance_drop_outline_only === true}
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
                    <Label htmlFor={`${fieldId}-outline-length`} className="text-xs text-muted-foreground">
                      最小内容字符
                    </Label>
                    <Input
                      id={`${fieldId}-outline-length`}
                      type="number"
                      min={0}
                      max={200000}
                      value={patch.governance_drop_outline_min_content_chars ?? ''}
                      onChange={(event) => {
                        const value = readNumberOverride(event.currentTarget)
                        onPatchChange({
                          ...patch,
                          governance_drop_outline_min_content_chars: value,
                        })
                      }}
                      className="h-9 rounded-lg"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor={`${fieldId}-heading-ratio`} className="text-xs text-muted-foreground">
                      标题占比阈值
                    </Label>
                    <Input
                      id={`${fieldId}-heading-ratio`}
                      type="number"
                      min={0}
                      max={1}
                      step="any"
                      value={patch.governance_drop_outline_max_heading_ratio ?? ''}
                      onChange={(event) => {
                        const value = readNumberOverride(event.currentTarget)
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
                    <div className="text-xs text-muted-foreground">low_density</div>
                  </div>
                  <Switch
                    aria-label="低密度过滤"
                    checked={patch.governance_drop_low_density === true}
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
                  <Label htmlFor={`${fieldId}-density`} className="text-xs text-muted-foreground">
                    密度阈值
                  </Label>
                  <Input
                    id={`${fieldId}-density`}
                    type="number"
                    min={0}
                    max={1}
                    step="any"
                    value={patch.governance_drop_low_density_threshold ?? ''}
                    onChange={(event) => {
                      const value = readNumberOverride(event.currentTarget)
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
                  <div className="text-xs text-muted-foreground">quarantine_on_drop</div>
                </div>
                <Switch
                  aria-label="触发质量过滤后隔离"
                  checked={patch.governance_quarantine_on_drop === true}
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
          </fieldset>
        </form>

        {tuneBusy && (
          <p role="status" className="text-sm text-muted-foreground">
            正在保存配置…
          </p>
        )}

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
          <Button type="submit" form={fieldId} variant="outline" className="rounded-xl" disabled={tuneDisabled}>
            <Settings2 className="size-4 mr-1" />
            保存配置
          </Button>
          <Button
            type="submit"
            form={fieldId}
            value="retry"
            variant="warning"
            className="rounded-xl"
            disabled={tuneDisabled}
          >
            <RotateCcw className="size-4 mr-1" />
            保存并重试
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
