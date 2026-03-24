import { Skeleton } from "@/components/ui/skeleton"

export default function GraphLoading() {
  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-6 md:p-8" role="status" aria-live="polite">
      <div className="max-w-6xl space-y-6">
        {/* Header skeleton */}
        <div className="flex items-center gap-4">
          <Skeleton className="h-10 w-10 rounded-xl" />
          <div className="space-y-2">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-4 w-64" />
          </div>
        </div>

        {/* Toolbar skeleton */}
        <div className="flex items-center gap-3">
          <Skeleton className="h-9 w-48 rounded-lg" />
          <Skeleton className="h-9 w-9 rounded-lg" />
          <Skeleton className="h-9 w-9 rounded-lg" />
        </div>

        {/* Graph canvas skeleton */}
        <Skeleton className="h-[480px] rounded-xl" />
      </div>
      <span className="sr-only">知识图谱加载中…</span>
    </div>
  )
}
