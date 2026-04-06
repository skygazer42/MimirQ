"use client"

import * as React from "react"
import * as PopoverPrimitive from "@radix-ui/react-popover"

import { cn } from "@/lib/utils"
import type { RadixRef } from "@/lib/radix-utils"

const Popover = PopoverPrimitive.Root

const PopoverTrigger = PopoverPrimitive.Trigger

const PopoverContent = React.forwardRef<
    RadixRef<typeof PopoverPrimitive.Content>,
    React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
>(({ className, align = "center", sideOffset = 4, ...props }, ref) => (
    <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
            ref={ref}
            align={align}
            sideOffset={sideOffset}
            className={cn(
                "z-50 w-72 rounded-lg border border-border/60 bg-popover p-4 text-popover-foreground shadow-strong outline-none origin-[var(--radix-popover-content-transform-origin)] transform-gpu will-change-[opacity,transform] data-[state=open]:animate-popover-in data-[state=closed]:animate-popover-out data-[side=bottom]:[--popover-enter-y:-6px] data-[side=top]:[--popover-enter-y:6px] data-[side=left]:[--popover-enter-y:0px] data-[side=right]:[--popover-enter-y:0px] motion-reduce:animate-none motion-reduce:transition-none",
                className
            )}
            {...props}
        />
    </PopoverPrimitive.Portal>
))
PopoverContent.displayName = PopoverPrimitive.Content.displayName

export { Popover, PopoverTrigger, PopoverContent }
