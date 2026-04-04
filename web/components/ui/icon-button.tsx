import * as React from "react"

import { Button, type ButtonProps } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/* Children icon should use size-4 for default, size-3.5 for sm */
type IconButtonProps = Readonly<Omit<ButtonProps, "children" | "size"> & {
  label: string
  children: React.ReactNode
}>

export function IconButton({
  label,
  className,
  children,
  asChild = false,
  type,
  ...props
}: IconButtonProps) {
  return (
    <Button
      {...props}
      asChild={asChild}
      size="icon"
      aria-label={label}
      title={label}
      // Icon buttons are rarely "submit" and can cause accidental form submits.
      type={asChild ? undefined : (type ?? "button")}
      className={cn("shrink-0", className)}
    >
      {children}
      <span className="sr-only">{label}</span>
    </Button>
  )
}
