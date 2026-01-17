"use client"

import { useQuery } from '@tanstack/react-query'
import { documentApi } from '@/lib/api-client'
import { Loader2, CheckCircle2, AlertCircle, X, ChevronUp, ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import { Button } from './ui/button'
import { ScrollArea } from './ui/scroll-area'

export function TaskCenter() {
  const [isOpen, setIsOpen] = useState(false)
  
  // Poll for active tasks globally
  const { data: documents = [] } = useQuery({
    queryKey: ['documents'],
    queryFn: async () => {
      const res = await documentApi.list({ limit: 100 })
      return res.items
    },
    // Passive update, rely on other components to trigger fetches or slow poll
    staleTime: 5000,
    refetchInterval: 5000 
  })

  const activeTasks = documents.filter(d => d.status === 'processing' || d.status === 'pending')
  const failedTasks = documents.filter(d => d.status === 'failed')
  
  const totalActive = activeTasks.length
  
  if (totalActive === 0 && failedTasks.length === 0) return null

  return (
    <div className="fixed bottom-4 right-20 z-50 flex flex-col items-end">
        {isOpen && (
            <div className="mb-2 w-80 bg-background border border-border rounded-xl shadow-2xl overflow-hidden animate-in slide-in-from-bottom-5 fade-in">
                <div className="p-3 border-b border-border bg-muted/50 flex justify-between items-center">
                    <h4 className="text-xs font-semibold">任务列表 ({totalActive})</h4>
                    <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setIsOpen(false)}>
                        <X className="h-3 w-3" />
                    </Button>
                </div>
                <ScrollArea className="h-48">
                    <div className="p-2 space-y-2">
                        {activeTasks.map(doc => (
                            <div key={doc.id} className="flex items-center gap-3 p-2 bg-secondary/30 rounded-lg">
                                <Loader2 className="h-4 w-4 animate-spin text-primary" />
                                <div className="flex-1 min-w-0">
                                    <p className="text-xs font-medium truncate">{doc.filename}</p>
                                    <div className="w-full h-1 bg-secondary mt-1.5 rounded-full overflow-hidden">
                                        <div className="h-full bg-primary transition-all duration-500" style={{ width: `${doc.processing_progress}%` }} />
                                    </div>
                                </div>
                                <span className="text-[10px] text-muted-foreground">{doc.processing_progress}%</span>
                            </div>
                        ))}
                        {failedTasks.map(doc => (
                            <div key={doc.id} className="flex items-center gap-3 p-2 bg-destructive/10 rounded-lg">
                                <AlertCircle className="h-4 w-4 text-destructive" />
                                <div className="flex-1 min-w-0">
                                    <p className="text-xs font-medium truncate text-destructive">{doc.filename}</p>
                                    <p className="text-[10px] text-destructive/80 truncate">处理失败</p>
                                </div>
                            </div>
                        ))}
                    </div>
                </ScrollArea>
            </div>
        )}

        <Button 
            onClick={() => setIsOpen(!isOpen)}
            className={cn(
                "rounded-full shadow-lg transition-all duration-300 gap-2 pr-4",
                isOpen ? "bg-primary text-primary-foreground" : "bg-background border border-border hover:bg-muted"
            )}
        >
            <div className="relative">
                <Loader2 className={cn("h-4 w-4", totalActive > 0 && "animate-spin")} />
                {totalActive > 0 && (
                    <span className="absolute -top-1 -right-1 flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-sky-500"></span>
                    </span>
                )}
            </div>
            <span className="text-xs font-medium">
                {totalActive > 0 ? `${totalActive} 个任务进行中` : '任务完成'}
            </span>
            {isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
        </Button>
    </div>
  )
}
