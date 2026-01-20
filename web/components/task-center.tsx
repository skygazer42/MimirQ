"use client"

import { useQuery } from '@tanstack/react-query'
import { documentApi } from '@/lib/api-client'
import { Loader2, AlertCircle, X, Ban, RotateCcw, ArrowUpRight, Settings2 } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import { Button } from './ui/button'
import { ScrollArea } from './ui/scroll-area'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { formatApiError } from '@/lib/api-errors'

export function TaskCenter() {
  const [isOpen, setIsOpen] = useState(false)
  const [acting, setActing] = useState<{ id: string; action: 'cancel' | 'retry' } | null>(null)
  const router = useRouter()
  
  // Poll for active tasks globally
  const { data: documents = [], refetch } = useQuery({
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
  const totalFailed = failedTasks.length
  const totalCount = totalActive + totalFailed
  
  if (totalCount === 0) return null

  const handleCancel = async (id: string) => {
    if (acting) return
    setActing({ id, action: 'cancel' })
    try {
      await documentApi.cancel(id)
      toast.success('已取消任务')
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '取消失败'))
    } finally {
      setActing(null)
    }
  }

  const handleRetry = async (id: string) => {
    if (acting) return
    setActing({ id, action: 'retry' })
    try {
      await documentApi.retry(id)
      toast.success('已触发重试')
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '重试失败'))
    } finally {
      setActing(null)
    }
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col items-end">
        {isOpen && (
            <div className="mb-2 w-80 bg-background border border-border rounded-xl shadow-2xl overflow-hidden animate-in slide-in-from-bottom-5 fade-in">
                <div className="p-3 border-b border-border bg-muted/50 flex justify-between items-center">
                    <div className="flex items-baseline gap-2">
                      <h4 className="text-sm font-semibold leading-none">任务中心</h4>
                      <div className="text-xs text-muted-foreground">
                        {totalActive > 0 && <span>进行中 {totalActive}</span>}
                        {totalActive > 0 && totalFailed > 0 && <span className="mx-1">·</span>}
                        {totalFailed > 0 && <span className="text-destructive">失败 {totalFailed}</span>}
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs gap-1"
                        onClick={() => {
                          router.push('/knowledge/ingestion')
                          setIsOpen(false)
                        }}
                      >
                        监控
                        <ArrowUpRight className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={() => setIsOpen(false)}
                        aria-label="关闭任务中心"
                        title="关闭"
                      >
                          <X className="h-3 w-3" />
                      </Button>
                    </div>
                </div>
                <ScrollArea className="h-48">
                    <div className="p-2 space-y-2">
                        {activeTasks.map(doc => (
                            <div key={doc.id} className="flex items-center gap-3 p-2 bg-secondary/30 rounded-lg">
                                <Loader2 className="h-4 w-4 animate-spin text-primary" />
                                <div className="flex-1 min-w-0">
                                    <p className="text-sm font-medium truncate leading-snug">{doc.filename}</p>
                                    <div className="w-full h-1 bg-secondary mt-1.5 rounded-full overflow-hidden">
                                        <div className="h-full bg-primary transition-all duration-500" style={{ width: `${doc.processing_progress}%` }} />
                                    </div>
                                </div>
                                <span className="text-xs tabular-nums text-muted-foreground">{doc.processing_progress}%</span>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-7 w-7"
                                  disabled={acting?.id === doc.id}
                                  onClick={() => handleCancel(doc.id)}
                                  aria-label="取消任务"
                                  title="取消"
                                >
                                  <Ban className="h-3.5 w-3.5" />
                                </Button>
                            </div>
                        ))}
                        {failedTasks.map(doc => (
                            <div key={doc.id} className="flex items-center gap-3 p-2 bg-destructive/10 rounded-lg">
                                <AlertCircle className="h-4 w-4 text-destructive" />
                                <div className="flex-1 min-w-0">
                                    <p className="text-sm font-medium truncate text-destructive leading-snug">{doc.filename}</p>
                                    <p className="text-xs text-destructive/80 truncate">处理失败</p>
                                </div>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-7 w-7"
                                  disabled={acting?.id === doc.id}
                                  onClick={() => handleRetry(doc.id)}
                                  aria-label="重试任务"
                                  title="重试"
                                >
                                  <RotateCcw className="h-3.5 w-3.5" />
                                </Button>
                            </div>
                        ))}
                    </div>
                </ScrollArea>
            </div>
        )}

        <Button
          variant="outline"
          size="icon"
          className={cn(
            "relative rounded-full h-12 w-12 shadow-2xl bg-background/80 backdrop-blur-md border-primary/20 hover:border-primary transition-all duration-300",
            isOpen && "bg-primary/10"
          )}
          onClick={() => setIsOpen(v => !v)}
          aria-label="任务中心"
          title="任务中心"
        >
          <Settings2 className="h-6 w-6 text-primary" />
          <span
            className={cn(
              "absolute -top-2 -right-2 inline-flex min-w-5 h-5 items-center justify-center rounded-full text-[10px] px-1 tabular-nums",
              totalFailed > 0 && totalActive === 0
                ? "bg-destructive text-destructive-foreground"
                : "bg-primary text-primary-foreground"
            )}
          >
            {totalCount}
          </span>
          {totalActive > 0 && (
            <span className="absolute -top-1 -left-1 flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-sky-500"></span>
            </span>
          )}
        </Button>
    </div>
  )
}
