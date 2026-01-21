import { cn } from "@/lib/utils"

type PageContainerProps = {
  children: React.ReactNode
  className?: string
  size?: "5xl" | "6xl" | "7xl" | "full"
}

const MAX_W: Record<NonNullable<PageContainerProps["size"]>, string> = {
  "5xl": "max-w-5xl",
  "6xl": "max-w-6xl",
  "7xl": "max-w-7xl",
  full: "max-w-none",
}

export function PageContainer({ children, className, size = "6xl" }: PageContainerProps) {
  return <div className={cn("mx-auto w-full", MAX_W[size], className)}>{children}</div>
}

