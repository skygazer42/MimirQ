import * as React from "react"

import { Button, type ButtonProps } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type A11yLabel =
  | { "aria-label": string; "aria-labelledby"?: never }
  | { "aria-label"?: never; "aria-labelledby": string }

export type IconButtonProps = Omit<ButtonProps, "size"> &
  A11yLabel & {
    /**
     * Defaults to `ghost` because icon-only actions are usually secondary.
     */
    variant?: ButtonProps["variant"]
  }

export function IconButton({ className, variant = "ghost", ...props }: IconButtonProps) {
  return (
    <Button
      {...props}
      variant={variant}
      size="icon"
      className={cn(
        "rounded-lg text-muted-foreground hover:text-foreground",
        className
      )}
    />
  )
}

