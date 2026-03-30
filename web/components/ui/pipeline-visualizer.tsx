"use client"

import { FileText, ScanLine, Scissors, Database, CheckCircle2 } from "lucide-react"
import { useTranslations } from 'next-intl'
import { cn } from "@/lib/utils"

interface PipelineVisualizerProps {
  progress: number // 0 - 100
  stage?: string
  className?: string
}

function getStages(t: ReturnType<typeof useTranslations<'CommonUi'>>) {
  return [
    { id: 'upload', label: t('pipelineVisualizer.upload'), icon: FileText, threshold: 10 },
    { id: 'parse', label: t('pipelineVisualizer.parse'), icon: ScanLine, threshold: 40 },
    { id: 'chunk', label: t('pipelineVisualizer.chunk'), icon: Scissors, threshold: 70 },
    { id: 'index', label: t('pipelineVisualizer.index'), icon: Database, threshold: 90 },
  ]
}

export function PipelineVisualizer({ progress, stage, className }: Readonly<PipelineVisualizerProps>) {
  const t = useTranslations('CommonUi')
  const stages = getStages(t)
  // Calculate active stage index based on progress
  const clamped = Number.isFinite(progress) ? Math.max(0, Math.min(100, progress)) : 0
  const nextIndex = stages.findIndex((s) => clamped < s.threshold)
  const activeIndex = nextIndex === -1 ? stages.length - 1 : nextIndex
  const progressScale = clamped / 100
  
  return (
    <div className={cn("w-full py-4 select-none", className)}>
      <div className="relative flex justify-between items-center px-2">
        {/* Background Line */}
        <div className="absolute left-0 right-0 top-1/2 h-1 bg-secondary rounded-full -z-10" />
        
        {/* Progress Line (transform-only; avoids animating layout width) */}
        <div
          aria-hidden="true"
          className="absolute left-0 right-0 top-1/2 h-1 bg-primary rounded-full -z-10 origin-left transition-transform duration-200 ease-out motion-reduce:transition-none"
          style={{ transform: `scaleX(${progressScale})` }}
        />

        {/* Nodes */}
        {stages.map((s, idx) => {
            const Icon = s.icon
            const isActive = idx <= activeIndex
            const isCompleted = idx < activeIndex || clamped >= 100

            return (
                <div key={s.id} className="relative flex flex-col items-center gap-2">
                    <div
                      className={cn(
                        "w-8 h-8 rounded-full flex items-center justify-center border-2 shadow-sm z-10 transition-transform transition-colors duration-200 ease-out motion-reduce:transition-none",
                        isActive && "scale-110",
                        (() => {
    if (isCompleted) {
        return "bg-primary text-primary-foreground border-primary";
    }
    else if (isActive) {
            return "bg-background text-primary border-primary ring-4 ring-primary/10";
        }
        else {
            return "bg-secondary text-muted-foreground border-transparent";
        }
})()
                      )}
                    >
                      {isCompleted ? <CheckCircle2 className="w-5 h-5" /> : <Icon className="w-4 h-4" />}
                    </div>
                    
                    <span className={cn(
                        "absolute top-10 text-[10px] font-medium whitespace-nowrap transition-colors duration-200 motion-reduce:transition-none",
                        isActive ? "text-primary" : "text-muted-foreground"
                    )}>
                        {s.label}
                    </span>
                </div>
            )
        })}
      </div>
    </div>
  )
}
