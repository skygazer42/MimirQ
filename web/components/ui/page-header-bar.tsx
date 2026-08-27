import { cn } from "@/lib/utils"

type PageHeaderBarProps = {
  children: React.ReactNode
  className?: string
}

export function PageHeaderBar({ children, className }: Readonly<PageHeaderBarProps>) {
  return (
    <div
      className={cn(
        "sticky top-0 z-20 border-b border-foreground/15 bg-background supports-[padding:env(safe-area-inset-top)]:pt-[env(safe-area-inset-top)]",
        className
      )}
    >
      {children}
    </div>
  )
}
