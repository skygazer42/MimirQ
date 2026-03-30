import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-medium ring-offset-background transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm hover:shadow-md",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90 shadow-sm hover:shadow-md",
        success:
          "bg-success text-success-foreground hover:bg-success/90 shadow-sm hover:shadow-md",
        warning:
          "bg-warning text-warning-foreground hover:bg-warning/90 shadow-sm hover:shadow-md",
        info:
          "bg-info text-info-foreground hover:bg-info/90 shadow-sm hover:shadow-md",
        outline:
          "border border-input bg-background hover:bg-accent hover:text-accent-foreground shadow-sm hover:shadow-md",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80 shadow-sm hover:shadow-md",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-11 px-4 py-2 sm:h-10",
        sm: "h-10 rounded-lg px-3 sm:h-9",
        lg: "h-12 rounded-xl px-8 sm:h-11",
        icon: "size-11 sm:size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export type ButtonProps = Readonly<
  React.ButtonHTMLAttributes<HTMLButtonElement> &
    VariantProps<typeof buttonVariants> & {
      asChild?: boolean
    }
>

function normalizeAccessibleLabel(value: string | undefined): string | undefined {
  const normalized = typeof value === "string" ? value.trim() : ""
  return normalized || undefined
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, title, "aria-label": ariaLabel, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    const iconAccessibleLabel =
      size === "icon"
        ? normalizeAccessibleLabel(ariaLabel) ?? normalizeAccessibleLabel(title)
        : undefined

    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        title={size === "icon" ? title ?? iconAccessibleLabel : title}
        aria-label={iconAccessibleLabel ?? ariaLabel}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
