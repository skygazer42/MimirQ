import { cn } from "@/lib/utils"

type PageHeaderBarProps = {
  children: React.ReactNode
  className?: string
}

export function PageHeaderBar({ children, className }: Readonly<PageHeaderBarProps>) {
  return (
    <div
      className={cn(
        "sticky top-0 z-20 border-b border-sidebar-border/70 bg-sidebar/80 backdrop-blur-xl shadow-sm shadow-black/5 supports-[padding:env(safe-area-inset-top)]:pt-[env(safe-area-inset-top)]",
        className
      )}
    >
      {children}
    </div>
  )
}
