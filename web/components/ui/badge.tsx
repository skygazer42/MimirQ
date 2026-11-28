import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded-md border border-transparent px-2 py-0.5 text-[11px] font-medium tabular-nums transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-ring/60 focus:ring-offset-1',
  {
    variants: {
      variant: {
        default: 'border-border/75 bg-foreground/[0.06] text-foreground',
        secondary: 'border-border/65 bg-muted text-muted-foreground',
        destructive: 'border-destructive/22 bg-destructive/10 text-destructive',
        success: 'border-success/22 bg-success/10 text-success',
        warning: 'border-warning/28 bg-warning/12 text-warning',
        info: 'border-info/22 bg-info/10 text-info',
        soft: 'border-border/55 bg-muted/70 text-muted-foreground',
        outline: 'border-border bg-card text-foreground',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

type BadgeProps = React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof badgeVariants>

export function Badge({ className, variant, ...props }: Readonly<BadgeProps>) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}
