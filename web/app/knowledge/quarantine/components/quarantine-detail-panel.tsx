'use client'

import { Badge } from '@/components/ui/badge'
import { formatFileSize } from '@/lib/utils'
import type { Document } from '@/types'

import { TYPO_EYEBROW } from '../constants'
import {
  buildReviewAdvice,
  getDropReasons,
  reasonLabel,
} from '../quarantine-signals'

interface QuarantineDetailPanelProps {
  selected: Document | null
}

export function QuarantineDetailPanel({
  selected,
}: Readonly<QuarantineDetailPanelProps>) {
  if (!selected) return null

  return (
    <div className="space-y-6">
      <div className="min-w-0">
        <div className={TYPO_EYEBROW}>Audit Abstract</div>
        <div className="mt-2 grid grid-cols-2 gap-3 rounded-lg border border-foreground/10 bg-background/70 p-4">
          {[
            { label: '文档 ID', value: selected.id.slice(0, 12) + '...' },
            { label: '数据集', value: selected.dataset_id || '-' },
            { label: '文件体积', value: formatFileSize(selected.file_size) },
            { label: '切片数量', value: String(selected.chunk_count ?? 0) },
          ].map((item) => (
            <div key={item.label} className="space-y-1">
              <div className="text-[10px] font-medium uppercase text-muted-foreground/60">
                {item.label}
              </div>
              <div className="break-words text-xs font-mono font-medium text-foreground/90">
                {item.value}
              </div>
            </div>
          ))}
        </div>
      </div>

      {selected.error_message && (
        <div className="rounded-lg border border-warning/30 bg-warning/5 p-4">
          <div className="text-[10px] font-medium uppercase text-warning">
            隔离原因 / RISKS
          </div>
          <div className="mt-2 break-words text-xs font-mono leading-relaxed text-warning/80">
            {selected.error_message}
          </div>
        </div>
      )}

      <div className="rounded-lg border border-foreground/10 bg-background/70 p-4">
        <div className={TYPO_EYEBROW}>处置建议 / ADVICE</div>
        <div className="mt-3 space-y-3">
          {buildReviewAdvice(selected).map((tip) => (
            <div
              key={tip}
              className="flex items-start gap-3 text-[13px] font-medium text-foreground/80 leading-relaxed"
            >
              <div className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-sm bg-warning" />
              <div>{tip}</div>
            </div>
          ))}
        </div>
      </div>

      {getDropReasons(selected).length > 0 ? (
        <div className="rounded-lg border border-foreground/10 bg-muted/30 p-4">
          <div className="text-[10px] font-medium uppercase text-muted-foreground/60">
            命中规则 / RULES
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {getDropReasons(selected).map((reason) => (
              <Badge
                key={reason}
                variant="secondary"
                className="rounded-lg border border-warning/20 bg-warning/10 px-2 py-1 text-[10px] font-medium uppercase text-warning"
              >
                {reasonLabel(reason)}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
