import { Skeleton } from "@/components/ui/skeleton"

export default function Loading() {
  return (
    <div className="flex h-screen overflow-hidden bg-background" role="status" aria-live="polite">
      {/* Left navigation skeleton (desktop only) */}
      <aside className="hidden md:flex w-[280px] flex-col border-r border-border p-4">
        <div className="flex items-center gap-3 pb-4">
          <Skeleton className="h-9 w-9 rounded-xl" />
          <div className="space-y-2">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-2 w-16" />
          </div>
        </div>

        <Skeleton className="h-11 rounded-2xl" />

        <div className="mt-5 space-y-2">
          {Array.from({ length: 9 }).map((_, i) => (
            <Skeleton key={i} className="h-9 rounded-lg" />
          ))}
        </div>

        <div className="mt-auto pt-4">
          <Skeleton className="h-14 rounded-xl" />
        </div>
      </aside>

      {/* Main content skeleton */}
      <main id="main-content" tabIndex={-1} className="flex-1 overflow-y-auto p-6">
        <div className="max-w-5xl space-y-6">
          <div className="space-y-3">
            <Skeleton className="h-7 w-56" />
            <Skeleton className="h-4 w-[420px] max-w-full" />
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-28 rounded-xl" />
            ))}
          </div>

          <div className="space-y-3">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-44 rounded-xl" />
          </div>
        </div>

        <span className="sr-only">页面加载中…</span>
      </main>
    </div>
  )
}

