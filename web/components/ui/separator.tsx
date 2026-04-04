"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

type SeparatorProps = Readonly<
  React.HTMLAttributes<HTMLDivElement> & {
    orientation?: "horizontal" | "vertical"
  }
>

const Separator = React.forwardRef<
  HTMLDivElement,
  SeparatorProps
>(({ className, orientation = "horizontal", ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "shrink-0 bg-border/60",
      orientation === "horizontal" ? "h-[1px] w-full" : "h-full w-[1px]",
      className
    )}
    {...props}
  />
))
Separator.displayName = "Separator"

export { Separator }
