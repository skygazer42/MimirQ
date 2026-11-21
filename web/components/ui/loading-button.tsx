import * as React from 'react'

import { Button, type ButtonProps } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type LoadingButtonProps = Omit<ButtonProps, 'asChild'> & { loading: boolean }

export const LoadingButton = React.forwardRef<HTMLButtonElement, LoadingButtonProps>(
  ({ loading, disabled, className, children, type = 'button', ...props }, ref) => (
    <Button
      {...props}
      ref={ref}
      asChild={false}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading}
      className={cn('relative', className)}
    >
      <span className={cn('inline-flex items-center gap-[inherit]', loading && 'opacity-0')}>{children}</span>
      {loading ? (
        <span aria-hidden="true" className="absolute inset-0 flex items-center justify-center">
          •••
        </span>
      ) : null}
    </Button>
  ),
)
LoadingButton.displayName = 'LoadingButton'
