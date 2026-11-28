import * as React from 'react'

import { cn } from '@/lib/utils'

type InputProps = React.InputHTMLAttributes<HTMLInputElement>

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, type, ...props }, ref) => {
  return (
    <input
      type={type}
      className={cn(
        'flex h-11 w-full rounded-md border border-input bg-card px-3 py-2 text-base text-foreground shadow-[0_1px_2px_hsl(var(--foreground)/0.03)] transition-[border-color,box-shadow] duration-150 placeholder:text-muted-foreground hover:border-foreground/25 focus-visible:outline-none focus-visible:border-accent/60 focus-visible:ring-2 focus-visible:ring-ring/20 focus-visible:ring-offset-0 disabled:cursor-not-allowed disabled:opacity-50 sm:h-9 sm:text-sm aria-[invalid=true]:border-destructive/60 aria-[invalid=true]:focus-visible:ring-destructive/25',
        className,
      )}
      ref={ref}
      {...props}
    />
  )
})
Input.displayName = 'Input'

export { Input }
