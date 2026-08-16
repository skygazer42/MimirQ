'use client'

import { AnimatePresence, motion } from 'framer-motion'
import { CircleAlert, ShieldCheck } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { PrecheckEmbeddingAdvisoryView } from '@/lib/precheck-embedding-advisories'

import type { IngestionMode } from '@/app/knowledge/ingestion/types'

type PrecheckSignalsPanelProps = {
  mode: IngestionMode
  successPulseVisible: boolean
  advisories: PrecheckEmbeddingAdvisoryView[]
}

export function PrecheckSignalsPanel({
  advisories,
  mode,
  successPulseVisible,
}: Readonly<PrecheckSignalsPanelProps>) {
  const showAdvisories = mode === 'sales-audit' && advisories.length > 0
  if (!successPulseVisible && !showAdvisories) return null

  return (
    <>
      <AnimatePresence>
        {successPulseVisible ? (
          <motion.div
            initial={{ opacity: 0, scaleX: 0.92 }}
            animate={{ opacity: 1, scaleX: 1 }}
            exit={{ opacity: 0 }}
            className="pointer-events-none relative mt-3 overflow-hidden rounded-[1.1rem] border border-success/15 bg-success/8 px-3 py-2.5"
          >
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(16,185,129,0.24),transparent_62%)]" />
            <div className="relative flex items-center gap-2 text-[12px] text-success">
              <ShieldCheck className="h-4 w-4" />
              入库确认反馈：当前数据集已出现健康可入库样本，可继续批量确认。
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {showAdvisories ? (
        <div className="mt-3 rounded-[1.1rem] border border-warning/20 bg-warning/[0.08] px-3 py-2.5">
          <div className="flex items-start gap-2 text-[12px] text-warning">
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="min-w-0">
              <div className="font-medium text-foreground">
                预检发现 embedding 建议
              </div>
              <div className="mt-1 text-[11px] leading-4 text-muted-foreground">
                当前摘要提示该语料更适合特定向量模型。这只是 warning，不表示系统已经自动切换模型。
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {advisories.flatMap((advisory) => {
                  const chips = [
                    `code=${advisory.code}`,
                    advisory.effectiveEmbedding
                      ? `current=${advisory.effectiveEmbedding}`
                      : null,
                    ...advisory.recommendedModelIds.map(
                      (modelId) => `recommended=${modelId}`
                    ),
                  ].filter(Boolean) as string[]
                  return chips.map((chip) => (
                    <span
                      key={`${advisory.code}-${chip}`}
                      className={cn(
                        'rounded-full border border-warning/20 bg-background/72 px-2 py-0.5 text-[10px] font-medium text-warning'
                      )}
                    >
                      {chip}
                    </span>
                  ))
                })}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </>
  )
}
