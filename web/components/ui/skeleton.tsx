import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'

import { cn } from '@/lib/utils'

type SkeletonProps = React.HTMLAttributes<HTMLDivElement> & { asChild?: boolean }

export function Skeleton({ className, asChild = false, ...props }: Readonly<SkeletonProps>) {
  const Component = asChild ? Slot : 'div'
  return (
    <Component
      className={cn('animate-pulse motion-reduce:animate-none rounded-lg bg-foreground/[0.04]', className)}
      {...props}
    />
  )
}
