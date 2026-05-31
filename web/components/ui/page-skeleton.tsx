import { cn } from "@/lib/utils"
import { Skeleton } from "@/components/ui/skeleton"

const DEFAULT_STAT_SKELETON_KEYS = ["stat-a", "stat-b", "stat-c"] as const
const DENSE_STAT_SKELETON_KEYS = ["stat-a", "stat-b", "stat-c", "stat-d"] as const
const DEFAULT_CONTENT_SKELETON_KEYS = ["content-a", "content-b", "content-c", "content-d"] as const
const DENSE_CONTENT_SKELETON_KEYS = ["content-a", "content-b", "content-c", "content-d", "content-e", "content-f"] as const

type PageSkeletonProps = {
  density?: "default" | "system-dense"
  className?: string
}

export function PageSkeleton({ density = "default", className }: Readonly<PageSkeletonProps>) {
  const isDense = density === "system-dense"

  return (
    <div className={cn("space-y-4", isDense && "space-y-3", className)}>
      {/* Header skeleton */}
      <div className={cn("flex items-center gap-3", isDense ? "px-1" : "px-2")}>
        <Skeleton className={cn(isDense ? "size-9 rounded-lg" : "size-12 rounded-xl")} />
        <div className="space-y-2 flex-1">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-3 w-72" />
        </div>
      </div>

      {/* Stats row skeleton */}
      <div className={cn("grid gap-3", isDense ? "grid-cols-4" : "grid-cols-3")}>
        {(isDense ? DENSE_STAT_SKELETON_KEYS : DEFAULT_STAT_SKELETON_KEYS).map((key) => (
          <Skeleton key={key} className={cn(isDense ? "h-16 rounded-lg" : "h-20 rounded-xl")} />
        ))}
      </div>

      {/* Content skeleton */}
      <div className="space-y-3">
        {(isDense ? DENSE_CONTENT_SKELETON_KEYS : DEFAULT_CONTENT_SKELETON_KEYS).map((key) => (
          <Skeleton key={key} className={cn(isDense ? "h-10 rounded-lg" : "h-14 rounded-xl")} />
        ))}
      </div>
    </div>
  )
}
