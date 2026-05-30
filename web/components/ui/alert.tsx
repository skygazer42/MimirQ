import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"
import type { RadixRef } from "@/lib/radix-utils"

const alertVariants = cva(
  "relative w-full rounded-lg border border-l-4 p-4 [&>svg~*]:pl-7 [&>svg]:absolute [&>svg]:left-4 [&>svg]:top-4 [&>svg]:text-foreground/80",
  {
    variants: {
      variant: {
        default: "bg-card text-foreground border-border border-l-border",
        success: "bg-success/10 border-success/25 border-l-success text-foreground [&>svg]:text-success",
        warning: "bg-warning/10 border-warning/25 border-l-warning text-foreground [&>svg]:text-warning",
        info: "bg-info/10 border-info/25 border-l-info text-foreground [&>svg]:text-info",
        destructive: "bg-destructive/10 border-destructive/25 border-l-destructive text-foreground [&>svg]:text-destructive",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface AlertProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertVariants> {}

export const Alert = React.forwardRef<HTMLDivElement, AlertProps>(function Alert(
  { className, variant, ...props },
  ref
) {
  return (
    <div
      ref={ref}
      role="alert"
      className={cn(alertVariants({ variant }), className)}
      {...props}
    />
  )
})

export const AlertTitle = React.forwardRef<
  RadixRef<"h5">,
  React.ComponentPropsWithoutRef<"h5">
>(function AlertTitle({ className, children, ...props }, ref) {
  return (
    <h5
      ref={ref}
      className={cn("mb-1 font-medium leading-none ", className)}
      {...props}
    >
      {children}
    </h5>
  )
})

export const AlertDescription = React.forwardRef<
  RadixRef<"div">,
  React.ComponentPropsWithoutRef<"div">
>(function AlertDescription({ className, ...props }, ref) {
  return (
    <div
      ref={ref}
      className={cn("text-sm leading-relaxed text-muted-foreground", className)}
      {...props}
    />
  )
})
