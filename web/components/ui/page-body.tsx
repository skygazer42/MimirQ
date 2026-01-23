import { cn } from "@/lib/utils"

type PageBodyProps = {
  children: React.ReactNode
  className?: string
}

export function PageBody({ children, className }: PageBodyProps) {
  return (
    <section
      data-page-scroll-container="true"
      className={cn(
        "flex-1 min-h-0 overflow-y-auto overscroll-contain px-6 md:px-8 pb-8 no-scrollbar",
        className
      )}
    >
      {children}
    </section>
  )
}
