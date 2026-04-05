import * as React from 'react'

import { Button, type ButtonProps } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const CreateDatasetButton = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ children = '新建数据集', className, ...props }, ref) => {
    return (
      <Button
        ref={ref}
        className={cn(
          'group h-auto rounded-full border-[8px] border-[#c0dfff] bg-[#006aff] px-5 py-3 text-white shadow-[0_18px_34px_-22px_rgba(0,106,255,1)] transition-all duration-300 hover:border-[#b1d8ff] hover:bg-[#1b7aff] hover:shadow-[0_22px_40px_-22px_rgba(27,122,255,1)] active:border-[5px] focus-visible:ring-4 focus-visible:ring-[#c0dfff]/60 focus-visible:ring-offset-2 dark:border-[#5d9bff] dark:hover:border-[#84b6ff] dark:focus-visible:ring-[#5d9bff]/35 motion-reduce:transition-none md:px-8 md:py-4',
          className
        )}
        {...props}
      >
        <span className="text-[1rem] font-bold tracking-[0.06em] md:text-[1.3rem]">
          {children}
        </span>
        <span className="flex h-full w-fit items-center justify-center pt-[5px]" aria-hidden="true">
          <svg
            viewBox="0 0 50 30"
            className="h-[22px] w-[36px] origin-left md:h-[30px] md:w-[50px] motion-safe:group-hover:[animation:dataset-jello-vertical_0.9s_both] motion-reduce:transform-none"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              d="M4 15H31.5"
              stroke="currentColor"
              strokeWidth="3.75"
              strokeLinecap="round"
            />
            <path
              d="M28.5 5.5L45 15L28.5 24.5"
              stroke="currentColor"
              strokeWidth="3.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      </Button>
    )
  }
)

CreateDatasetButton.displayName = 'CreateDatasetButton'

export { CreateDatasetButton }
