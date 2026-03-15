import { cn } from "@/lib/utils"

type AppBackgroundProps = {
  className?: string
}

export function AppBackground({ className }: Readonly<AppBackgroundProps>) {
  return (
    // NOTE: Keep this layer from creating window-level scrollbars (avoid negative offsets + heavy blurs).
    <div aria-hidden="true" className={cn("pointer-events-none fixed inset-0 z-0 overflow-hidden", className)}>
      <div className="absolute inset-0 bg-background" />

      {/* Lightweight “instrument paper” grid; token-driven and gradient-free. */}
      <svg
        className="absolute inset-0 h-full w-full opacity-25 dark:opacity-20"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <pattern id="mimirq-grid" width="48" height="48" patternUnits="userSpaceOnUse">
            <path d="M48 0H0V48" fill="none" className="stroke-border/60" strokeWidth="1" />
            <circle cx="24" cy="24" r="1" className="fill-border/70" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#mimirq-grid)" />
      </svg>
    </div>
  )
}
