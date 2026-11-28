import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'
import type { RadixRef } from '@/lib/radix-utils'

const alertVariants = cva(
  'relative w-full rounded-lg border border-l-[3px] px-4 py-3 [&>svg~*]:pl-7 [&>svg]:absolute [&>svg]:left-3.5 [&>svg]:top-3.5 [&>svg]:text-foreground/80',
  {
    variants: {
      variant: {
        default: 'bg-card text-foreground border-border border-l-border',
        success: 'bg-card border-border border-l-success text-foreground [&>svg]:text-success',
        warning: 'bg-card border-border border-l-accent text-foreground [&>svg]:text-accent',
        info: 'bg-card border-border border-l-info text-foreground [&>svg]:text-info',
        destructive: 'bg-card border-border border-l-destructive/75 text-foreground [&>svg]:text-destructive',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

type AlertProps = React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>

export const Alert = React.forwardRef<HTMLDivElement, AlertProps>(function Alert(
  { className, variant, ...props },
  ref,
) {
  return <div ref={ref} role="alert" className={cn(alertVariants({ variant }), className)} {...props} />
})

export const AlertTitle = React.forwardRef<RadixRef<'h5'>, React.ComponentPropsWithoutRef<'h5'>>(function AlertTitle(
  { className, children, ...props },
  ref,
) {
  return (
    <h5 ref={ref} className={cn('mb-1 font-medium leading-none ', className)} {...props}>
      {children}
    </h5>
  )
})

export const AlertDescription = React.forwardRef<RadixRef<'div'>, React.ComponentPropsWithoutRef<'div'>>(
  function AlertDescription({ className, ...props }, ref) {
    return <div ref={ref} className={cn('text-sm leading-relaxed text-muted-foreground', className)} {...props} />
  },
)
