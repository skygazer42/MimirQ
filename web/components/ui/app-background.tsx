import { cn } from "@/lib/utils"

type AppBackgroundProps = {
  className?: string
}

export function AppBackground({ className }: Readonly<AppBackgroundProps>) {
  return (
    <div aria-hidden="true" className={cn("pointer-events-none fixed inset-0 z-0 overflow-hidden", className)}>
      <div className="absolute inset-0 bg-background" />

      {/* Subtle color accents in corners break the monotone feel */}
      <div className="absolute -top-[30%] -right-[20%] h-[800px] w-[800px] rounded-full bg-primary/[0.02] blur-[128px]" />
      <div className="absolute -bottom-[20%] -left-[15%] h-[700px] w-[700px] rounded-full bg-accent/[0.02] blur-[128px]" />

      {/* Lightweight "instrument paper" grid; token-driven. */}
      <svg
        className="absolute inset-0 h-full w-full opacity-25 dark:opacity-20"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <pattern id="mimirq-grid" width="64" height="64" patternUnits="userSpaceOnUse">
            <path d="M64 0H0V64" fill="none" className="stroke-border/60" strokeWidth="1" />
            <circle cx="32" cy="32" r="0.5" className="fill-border/70" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#mimirq-grid)" />
      </svg>
    </div>
  )
}
