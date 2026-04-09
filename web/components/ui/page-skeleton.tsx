import { cn } from "@/lib/utils"
import { Skeleton } from "@/components/ui/skeleton"

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
        {Array.from({ length: isDense ? 4 : 3 }).map((_, i) => (
          <Skeleton key={i} className={cn(isDense ? "h-16 rounded-lg" : "h-20 rounded-xl")} />
        ))}
      </div>

      {/* Content skeleton */}
      <div className="space-y-3">
        {Array.from({ length: isDense ? 6 : 4 }).map((_, i) => (
          <Skeleton key={i} className={cn(isDense ? "h-10 rounded-lg" : "h-14 rounded-xl")} />
        ))}
      </div>
    </div>
  )
}
