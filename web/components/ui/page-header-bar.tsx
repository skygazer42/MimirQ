import { cn } from "@/lib/utils"

type PageHeaderBarProps = {
  children: React.ReactNode
  className?: string
}

export function PageHeaderBar({ children, className }: PageHeaderBarProps) {
  return (
    <div
      className={cn(
        "sticky top-0 z-20 border-b border-border/60 bg-background/70 backdrop-blur-md shadow-sm shadow-black/5 supports-[padding:env(safe-area-inset-top)]:pt-[env(safe-area-inset-top)]",
        className
      )}
    >
      {children}
    </div>
  )
}
