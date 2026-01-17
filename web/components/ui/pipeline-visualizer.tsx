"use client"

import { motion } from "framer-motion"
import { FileText, ScanLine, Scissors, Database, CheckCircle2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface PipelineVisualizerProps {
  progress: number // 0 - 100
  stage?: string
  className?: string
}

const STAGES = [
  { id: 'upload', label: '上传', icon: FileText, threshold: 10 },
  { id: 'parse', label: '解析', icon: ScanLine, threshold: 40 },
  { id: 'chunk', label: '切片', icon: Scissors, threshold: 70 },
  { id: 'index', label: '索引', icon: Database, threshold: 90 },
]

export function PipelineVisualizer({ progress, stage, className }: PipelineVisualizerProps) {
  // Calculate active stage index based on progress
  const activeIndex = STAGES.findIndex(s => progress < s.threshold) === -1 ? STAGES.length - 1 : STAGES.findIndex(s => progress < s.threshold)
  
  return (
    <div className={cn("w-full py-4 select-none", className)}>
      <div className="relative flex justify-between items-center px-2">
        {/* Background Line */}
        <div className="absolute left-0 right-0 top-1/2 h-1 bg-secondary rounded-full -z-10" />
        
        {/* Animated Progress Line */}
        <motion.div 
            className="absolute left-0 top-1/2 h-1 bg-gradient-to-r from-primary to-cyan-400 rounded-full -z-10"
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ type: "spring", stiffness: 50, damping: 20 }}
        />

        {/* Nodes */}
        {STAGES.map((s, idx) => {
            const Icon = s.icon
            const isActive = idx <= activeIndex
            const isCompleted = idx < activeIndex || progress >= 100

            return (
                <div key={s.id} className="relative flex flex-col items-center gap-2">
                    <motion.div
                        initial={false}
                        animate={{
                            scale: isActive ? 1.1 : 1,
                            backgroundColor: isCompleted ? "var(--primary)" : isActive ? "var(--background)" : "var(--secondary)",
                            borderColor: isCompleted || isActive ? "var(--primary)" : "transparent"
                        }}
                        className={cn(
                            "w-8 h-8 rounded-full flex items-center justify-center border-2 shadow-sm z-10 transition-colors duration-300",
                            isCompleted ? "bg-primary text-primary-foreground border-primary" : 
                            isActive ? "bg-background text-primary border-primary ring-4 ring-primary/10" : 
                            "bg-secondary text-muted-foreground border-transparent"
                        )}
                    >
                        {isCompleted ? <CheckCircle2 className="w-5 h-5" /> : <Icon className="w-4 h-4" />}
                    </motion.div>
                    
                    <span className={cn(
                        "absolute top-10 text-[10px] font-medium whitespace-nowrap transition-colors duration-300",
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
