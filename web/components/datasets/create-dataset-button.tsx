import * as React from 'react'
import { Plus } from 'lucide-react'

import { Button, type ButtonProps } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const CreateDatasetButton = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ children = '新建数据集', className, ...props }, ref) => {
    return (
      <Button
        ref={ref}
        className={cn(
          'gap-1.5 rounded-full px-4 py-2.5 text-sm font-semibold shadow-sm',
          className
        )}
        {...props}
      >
        <Plus className="size-4" aria-hidden="true" />
        <span>{children}</span>
      </Button>
    )
  }
)

CreateDatasetButton.displayName = 'CreateDatasetButton'

export { CreateDatasetButton }
