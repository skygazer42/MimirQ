import { cn } from "@/lib/utils"

export function Kbd({ children, className }: Readonly<{ children: React.ReactNode; className?: string }>) {
  return (
    <kbd
      className={cn(
        "inline-flex h-6 select-none items-center rounded-md border border-border/70 bg-muted/60 px-2 font-mono text-[11px] text-muted-foreground shadow-soft",
        className
      )}
    >
      {children}
    </kbd>
  )
}
