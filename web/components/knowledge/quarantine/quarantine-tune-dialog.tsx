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
import { getDropReasons, getQuarantineSeverity, reasonLabel } from '@/app/knowledge/quarantine/quarantine-signals'
import styles from '@/app/knowledge/quarantine/quarantine.module.css'

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
      <DialogContent className={styles.tuneDialog} showCloseButton={!tuneBusy}>
        <DialogHeader className={styles.tuneHeader}>
          <DialogTitle className="flex items-center gap-2">
            <Settings2 className="size-4 text-muted-foreground" />
            调参回放
          </DialogTitle>
        </DialogHeader>

        <form
          id={fieldId}
          className={styles.tuneForm}
          onSubmit={(event) => {
            event.preventDefault()
            if (tuneDisabled) return
            const submitter = (event.nativeEvent as SubmitEvent).submitter
            onSave({ retryAfterSave: submitter instanceof HTMLButtonElement && submitter.value === 'retry' })
          }}
        >
          <fieldset disabled={tuneDisabled} className="min-w-0 space-y-5">
            <legend className="sr-only">文档处理配置</legend>
            <div className={styles.tunePreset}>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-medium text-foreground">推荐预设</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    关闭对应质量过滤器，让更多内容进入切块（仍建议人工抽检）。
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button type="button" size="sm" variant="outline" onClick={onApplyDisableQualityFilters}>
                    关闭质量过滤
                  </Button>
                  <Button type="button" size="sm" variant="outline" onClick={onResetRecommended}>
                    还原推荐
                  </Button>
                </div>
              </div>
            </div>

            <div className={styles.tuneGrid}>
              <div className="min-w-0 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium">大纲过滤</div>
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

              <div className="min-w-0 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium">低密度过滤</div>
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

            <div className="space-y-3 border-t pt-5">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium">隔离策略</div>
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
              <div className="text-xs text-muted-foreground">触发质量过滤时加入隔离队列，等待人工复核。</div>
            </div>
          </fieldset>
        </form>

        {tuneBusy && (
          <p role="status" className={styles.tuneBusy}>
            正在保存配置…
          </p>
        )}

        <DialogFooter className={styles.tuneFooter}>
          <DialogDescription className={styles.tuneDescription}>
            配置仅对「{target?.filename}」生效，保存后可重试入库。
            {target !== null && (
              <span className={styles.tuneSignals}>
                隔离原因：{getDropReasons(target).map(reasonLabel).join('、') || '待确认原因'} ·{' '}
                {getQuarantineSeverity(target)}风险
              </span>
            )}
          </DialogDescription>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={tuneBusy}>
            取消
          </Button>
          <Button type="submit" form={fieldId} variant="outline" disabled={tuneDisabled}>
            <Settings2 className="size-4" />
            保存配置
          </Button>
          <Button type="submit" form={fieldId} value="retry" className={styles.tunePrimary} disabled={tuneDisabled}>
            <RotateCcw className="size-4" />
            保存并重试
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
