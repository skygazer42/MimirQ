import { cn } from "@/lib/utils"

type PageBodyProps = {
  children: React.ReactNode
  className?: string
  compact?: boolean
  gutter?: "default" | "dense" | "none"
}

export function PageBody({
  children,
  className,
  compact = true,
  gutter = "default",
}: Readonly<PageBodyProps>) {
  const gutterClass =
    gutter === "none"
      ? "px-0"
      : gutter === "dense"
        ? compact
          ? "px-4 md:px-5 lg:px-6"
          : "px-4 md:px-5 lg:px-6"
        : compact
          ? "px-4 md:px-6"
          : "px-6 md:px-8"

  return (
    <section
      data-page-scroll-container="true"
      className={cn(
        "flex-1 min-h-0 overflow-y-auto overscroll-contain pt-4 pb-8 custom-scrollbar scroll-fade-bottom",
        gutterClass,
        className
      )}
    >
      {children}
    </section>
  )
}
