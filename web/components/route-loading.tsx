import { Loader2 } from 'lucide-react'

export function RouteLoading() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-[40vh] items-center justify-center gap-3 p-6 text-muted-foreground"
    >
      <Loader2 className="size-6 animate-spin motion-reduce:animate-none" aria-hidden="true" />
      <span className="text-sm font-medium">加载中…</span>
      <span className="sr-only">Loading</span>
    </div>
  )
}
