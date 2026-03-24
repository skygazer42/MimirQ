import { Skeleton } from "@/components/ui/skeleton"

const ROW_KEYS = ["r-1", "r-2", "r-3", "r-4", "r-5"]

export default function DatasetDetailLoading() {
  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-6 md:p-8" role="status" aria-live="polite">
      <div className="max-w-6xl space-y-6">
        {/* Header skeleton */}
        <div className="flex items-center gap-4">
          <Skeleton className="h-10 w-10 rounded-xl" />
          <div className="space-y-2">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-4 w-72" />
          </div>
        </div>

        {/* Tab bar skeleton */}
        <Skeleton className="h-10 w-96 max-w-full rounded-lg" />

        {/* Table skeleton */}
        <div className="space-y-3">
          <Skeleton className="h-10 rounded-lg" />
          {ROW_KEYS.map((key) => (
            <Skeleton key={key} className="h-14 rounded-lg" />
          ))}
        </div>
      </div>
      <span className="sr-only">数据集详情加载中…</span>
    </div>
  )
}
