import * as React from "react"

import { cn } from "@/lib/utils"

function Skeleton({ className, ...props }: Readonly<React.HTMLAttributes<HTMLDivElement>>) {
  return (
    <div
      className={cn(
        "animate-pulse motion-reduce:animate-none rounded-md bg-muted/50 relative overflow-hidden after:absolute after:inset-y-0 after:left-0 after:w-1/2 after:translate-x-[-100%] after:animate-shimmer after:bg-primary/[0.05] after:blur-xl",
        className
      )}
      {...props}
    />
  )
}

export { Skeleton }
