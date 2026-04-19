import { cn } from "@/lib/utils"

export function Kbd({ children, className }: Readonly<{ children: React.ReactNode; className?: string }>) {
  return (
    <kbd
      className={cn(
        "inline-flex h-[22px] select-none items-center rounded-md border border-border/60 bg-muted/60 px-1.5 font-mono text-[11px] font-normal text-muted-foreground tabular-nums shadow-[inset_0_-1px_0_0_hsl(var(--border)/0.5)]",
        className
      )}
    >
      {children}
    </kbd>
  )
}
