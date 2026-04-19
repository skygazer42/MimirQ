import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-md border border-transparent px-2 py-0.5 text-[11px] font-medium tracking-normal transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-ring/60 focus:ring-offset-1",
  {
    variants: {
      variant: {
        default:
          "bg-foreground/[0.07] text-foreground",
        secondary:
          "bg-muted text-muted-foreground",
        destructive:
          "bg-destructive/12 text-destructive",
        success:
          "bg-success/12 text-success",
        warning:
          "bg-warning/12 text-warning",
        info:
          "bg-info/12 text-info",
        soft:
          "bg-muted/60 text-muted-foreground",
        outline: "border-border bg-transparent text-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: Readonly<BadgeProps>) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
