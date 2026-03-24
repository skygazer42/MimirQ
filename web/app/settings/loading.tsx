import { Skeleton } from "@/components/ui/skeleton"

const SECTION_KEYS = ["s-1", "s-2", "s-3"]

export default function SettingsLoading() {
  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-6 md:p-8" role="status" aria-live="polite">
      <div className="max-w-6xl space-y-6">
        {/* Header skeleton */}
        <div className="flex items-center gap-4">
          <Skeleton className="h-10 w-10 rounded-xl" />
          <div className="space-y-2">
            <Skeleton className="h-6 w-32" />
            <Skeleton className="h-4 w-56" />
          </div>
        </div>

        {/* Settings sections skeleton */}
        {SECTION_KEYS.map((key) => (
          <div key={key} className="space-y-3">
            <Skeleton className="h-5 w-28" />
            <Skeleton className="h-24 rounded-xl" />
          </div>
        ))}
      </div>
      <span className="sr-only">设置页加载中…</span>
    </div>
  )
}
