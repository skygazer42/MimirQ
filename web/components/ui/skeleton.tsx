import * as React from "react"

import { cn } from "@/lib/utils"

function Skeleton({ className, ...props }: Readonly<React.HTMLAttributes<HTMLDivElement>>) {
  return (
    <div
      className={cn(
        "animate-pulse motion-reduce:animate-none rounded-lg bg-foreground/[0.04]",
        className
      )}
      {...props}
    />
  )
}

export { Skeleton }
