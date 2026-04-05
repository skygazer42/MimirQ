import * as React from 'react'
import { ArrowRight } from 'lucide-react'

import { Button, type ButtonProps } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const CreateDatasetButton = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ children = '新建数据集', className, ...props }, ref) => {
    return (
      <Button
        ref={ref}
        className={cn(
          'group h-auto rounded-full border-[6px] border-[#c0dfff] bg-[#006aff] px-4 py-2.5 text-white shadow-[0_16px_32px_-20px_rgba(0,106,255,0.95)] transition-[background-color,border-color,box-shadow,transform] duration-300 hover:border-[#b1d8ff] hover:bg-[#1b7aff] hover:shadow-[0_20px_36px_-20px_rgba(27,122,255,0.95)] motion-safe:hover:-translate-y-0.5 active:translate-y-0.5 active:shadow-[inset_0_3px_14px_rgba(0,0,0,0.16)] focus-visible:ring-4 focus-visible:ring-[#c0dfff]/60 focus-visible:ring-offset-2 dark:border-[#5d9bff] dark:hover:border-[#84b6ff] dark:focus-visible:ring-[#5d9bff]/35 motion-reduce:transition-none',
          className
        )}
        {...props}
      >
        <span className="text-[0.95rem] font-bold tracking-[0.02em]">
          {children}
        </span>
        <span className="flex w-fit items-center justify-center pt-0.5" aria-hidden="true">
          <ArrowRight className="h-5 w-7 origin-left motion-safe:group-hover:[animation:dataset-jello-vertical_0.9s_both] motion-reduce:transform-none" />
        </span>
      </Button>
    )
  }
)

CreateDatasetButton.displayName = 'CreateDatasetButton'

export { CreateDatasetButton }
