import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-full border border-border/60 px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary/85 text-primary-foreground hover:bg-primary/75",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/90",
        success:
          "border-transparent bg-success text-success-foreground hover:bg-success/90",
        warning:
          "border-transparent bg-warning text-warning-foreground hover:bg-warning/90",
        info:
          "border-transparent bg-info text-info-foreground hover:bg-info/90",
        accent:
          "border-transparent bg-accent text-accent-foreground hover:bg-accent/90",
        teal:
          "border-transparent bg-teal text-teal-foreground hover:bg-teal/90",
        indigo:
          "border-transparent bg-indigo text-indigo-foreground hover:bg-indigo/90",
        soft:
          "bg-muted/60 text-foreground border-border/60 hover:bg-muted/80",
        outline: "bg-transparent text-foreground",
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
