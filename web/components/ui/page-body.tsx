import { cn } from "@/lib/utils"

type PageBodyProps = {
  children: React.ReactNode
  className?: string
  compact?: boolean
}

export function PageBody({ children, className, compact = true }: Readonly<PageBodyProps>) {
  return (
    <section
      data-page-scroll-container="true"
      className={cn(
        "flex-1 min-h-0 overflow-y-auto overscroll-contain pb-8 no-scrollbar",
        compact ? "px-4 md:px-6" : "px-6 md:px-8",
        className
      )}
    >
      {children}
    </section>
  )
}
