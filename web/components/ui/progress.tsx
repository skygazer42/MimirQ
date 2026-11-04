'use client'

import * as React from 'react'
import * as ProgressPrimitive from '@radix-ui/react-progress'

import { cn } from '@/lib/utils'

const Progress = React.forwardRef<
  React.ComponentRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root>
>(({ className, value, max, ...props }, ref) => {
  // Match Radix's range validation for the indicator; Root keeps its own diagnostics and ARIA policy.
  const maximum = typeof max === 'number' && !Number.isNaN(max) && max > 0 ? max : 100
  const percentage =
    typeof value === 'number' && !Number.isNaN(value) && value >= 0 && value <= maximum ? (value / maximum) * 100 : 0

  return (
    <ProgressPrimitive.Root
      ref={ref}
      value={value}
      max={max}
      className={cn('relative h-2 w-full overflow-hidden rounded-full bg-secondary', className)}
      {...props}
    >
      <ProgressPrimitive.Indicator
        className="h-full bg-primary rounded-full transition-transform duration-300 ease-out"
        style={{ transform: `translateX(-${100 - percentage}%)` }}
      />
    </ProgressPrimitive.Root>
  )
})
Progress.displayName = ProgressPrimitive.Root.displayName

export { Progress }
