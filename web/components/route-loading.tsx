import { Loader2 } from 'lucide-react'

export function RouteLoading() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center gap-3 p-6" aria-live="polite">
      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      <span className="text-sm text-muted-foreground">加载中...</span>
    </div>
  )
}
