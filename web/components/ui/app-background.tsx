import { cn } from "@/lib/utils"

type AppBackgroundProps = {
  className?: string
}

export function AppBackground({ className }: AppBackgroundProps) {
  return (
    <div aria-hidden="true" className={cn("pointer-events-none fixed inset-0 z-0", className)}>
      {/* Base wash */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-background via-background to-muted/40 dark:to-muted/20" />

      {/* Dot grid texture */}
      <div className="absolute inset-0 opacity-50 dark:opacity-25 bg-[radial-gradient(hsl(var(--border))_1px,transparent_1px)] [background-size:32px_32px]" />

      {/* Soft brand glows */}
      <div className="absolute -top-48 left-1/4 h-[720px] w-[720px] rounded-full bg-primary/10 blur-[120px]" />
      <div className="absolute -bottom-56 right-1/4 h-[640px] w-[640px] rounded-full bg-primary/5 blur-[140px]" />
    </div>
  )
}

