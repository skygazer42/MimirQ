import { useTranslations } from 'next-intl'

import { Skeleton } from "@/components/ui/skeleton"
import { AppBackground } from "@/components/ui/app-background"

const NAV_SKELETON_KEYS = ["nav-1", "nav-2", "nav-3", "nav-4", "nav-5", "nav-6", "nav-7", "nav-8", "nav-9"]
const CARD_SKELETON_KEYS = ["card-1", "card-2", "card-3", "card-4", "card-5", "card-6"]

export default function Loading() {
  const t = useTranslations('RouteBoundaries')

  return (
    <div className="relative flex h-dvh overflow-hidden bg-background" role="status" aria-live="polite">
      <AppBackground />

      <div className="relative z-10 flex h-full w-full overflow-hidden">
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
            {NAV_SKELETON_KEYS.map((key) => (
              <Skeleton key={key} className="h-9 rounded-lg" />
            ))}
          </div>

          <div className="mt-auto pt-4">
            <Skeleton className="h-14 rounded-xl" />
          </div>
        </aside>

        {/* Main content skeleton */}
        <main id="main-content" tabIndex={-1} className="flex-1 min-h-0 overflow-y-auto overscroll-contain no-scrollbar p-6">
          <div className="max-w-5xl space-y-6">
            <div className="space-y-3">
              <Skeleton className="h-7 w-56" />
              <Skeleton className="h-4 w-[420px] max-w-full" />
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {CARD_SKELETON_KEYS.map((key) => (
                <Skeleton key={key} className="h-28 rounded-xl" />
              ))}
            </div>

            <div className="space-y-3">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-44 rounded-xl" />
            </div>
          </div>

          <span className="sr-only">{t("loading.pageSr")}</span>
        </main>
      </div>
    </div>
  )
}
