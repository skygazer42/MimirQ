import { Skeleton } from "@/components/ui/skeleton"

const CARD_KEYS = ["k-1", "k-2", "k-3", "k-4", "k-5", "k-6"]

export default function KnowledgeLoading() {
  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-6 md:p-8" role="status" aria-live="polite">
      <div className="max-w-6xl space-y-6">
        {/* Header skeleton */}
        <div className="flex items-center gap-4">
          <Skeleton className="h-10 w-10 rounded-xl" />
          <div className="space-y-2">
            <Skeleton className="h-6 w-36" />
            <Skeleton className="h-4 w-60" />
          </div>
        </div>

        {/* Search / toolbar skeleton */}
        <div className="flex items-center gap-3">
          <Skeleton className="h-10 flex-1 max-w-sm rounded-lg" />
          <Skeleton className="h-10 w-24 rounded-lg" />
        </div>

        {/* Card grid skeleton */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {CARD_KEYS.map((key) => (
            <Skeleton key={key} className="h-32 rounded-xl" />
          ))}
        </div>
      </div>
      <span className="sr-only">知识库加载中…</span>
    </div>
  )
}
