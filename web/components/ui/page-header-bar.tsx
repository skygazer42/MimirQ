import { cn } from "@/lib/utils"

type PageHeaderBarProps = {
  children: React.ReactNode
  className?: string
}

export function PageHeaderBar({ children, className }: PageHeaderBarProps) {
  return (
    <div
      className={cn(
        "sticky top-0 z-20 backdrop-blur-md bg-background/70 border-b border-border/60 shadow-sm shadow-black/5",
        className
      )}
    >
      {children}
    </div>
  )
}

