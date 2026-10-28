import * as React from "react"
import * as CheckboxPrimitive from "@radix-ui/react-checkbox"
import { Check, Minus } from "@/components/icons"

import { cn } from "@/lib/utils"
import type { RadixRef } from "@/lib/radix-utils"

const Checkbox = React.forwardRef<
  RadixRef<typeof CheckboxPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(({ className, ...props }, ref) => (
  <CheckboxPrimitive.Root
    ref={ref}
    className={cn(
      "peer h-4 w-4 shrink-0 rounded border border-muted-foreground/70 ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:border-foreground data-[state=checked]:bg-foreground data-[state=checked]:text-background data-[state=indeterminate]:border-foreground data-[state=indeterminate]:bg-foreground data-[state=indeterminate]:text-background",
      className
    )}
    {...props}
  >
    <CheckboxPrimitive.Indicator
      className="group/checkbox flex h-full w-full items-center justify-center text-current"
    >
      <Check strokeWidth={2.3} className="h-full w-full group-data-[state=indeterminate]/checkbox:hidden" />
      <Minus strokeWidth={2.3} className="hidden h-full w-full group-data-[state=indeterminate]/checkbox:block" />
    </CheckboxPrimitive.Indicator>
  </CheckboxPrimitive.Root>
))
Checkbox.displayName = CheckboxPrimitive.Root.displayName

export { Checkbox }
