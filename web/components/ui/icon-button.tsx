import * as React from "react"

import { Button, type ButtonProps } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type IconButtonProps = Omit<ButtonProps, "children" | "size"> & {
  label: string
  children: React.ReactNode
}

export function IconButton({ label, className, children, ...props }: IconButtonProps) {
  return (
    <Button
      {...props}
      size="icon"
      aria-label={label}
      title={label}
      className={cn("shrink-0", className)}
    >
      {children}
      <span className="sr-only">{label}</span>
    </Button>
  )
}

